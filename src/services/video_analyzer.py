"""
VideoAnalyzer: unified video analysis module.
Interface: analyze(video_path, options) → AnalysisResult

Replaces scattered video_processor.py + video_indexer.py logic.
Whisper transcription + Tesseract OCR + optional GPT-4o Vision.
"""
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.config import config
from src.errors import RetryableError, PermanentError
from src.security.sanitizer import sanitize_text, validate_upload

logger = logging.getLogger("brand-guardian.video-analyzer")


@dataclass
class TranscriptSegment:
    text: str
    start: float
    end: float


@dataclass
class OcrFrame:
    text: str
    timestamp: float


@dataclass
class VisualContext:
    description: str
    timestamp: float


@dataclass
class AnalyzerOptions:
    enable_visual: bool = False
    frame_interval_seconds: float = 5.0


@dataclass
class AnalysisResult:
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    ocr_frames: list[OcrFrame] = field(default_factory=list)
    visual_context: list[VisualContext] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ponytail: GPT-4o Vision prompt for frame description — kept minimal and factual.
_VISION_SYSTEM_PROMPT = (
    "You are analyzing a single frame from a video advertisement. "
    "Describe ONLY what is visually present: text overlays, products shown, "
    "people, claims displayed on screen, logos, before/after imagery, "
    "disclaimers, and fine print. Be factual and concise. "
    "Do not interpret compliance or legality. Output plain text, max 3 sentences."
)


class VideoAnalyzer:
    """
    Unified video analysis. Call analyze() once, get everything back.
    """

    def analyze(self, video_path: str, options: AnalyzerOptions | None = None) -> AnalysisResult:
        """
        Extract all signals from a video file.
        Validates input, transcribes, runs OCR, and optionally describes frames.
        """
        if options is None:
            options = AnalyzerOptions()

        # Validate before doing any expensive work
        validate_upload(video_path)

        result = AnalysisResult()

        # 1. Whisper transcription
        result.transcript_segments = self._transcribe(video_path)
        result.metadata["transcript_char_count"] = sum(
            len(s.text) for s in result.transcript_segments
        )

        # 2. Extract frames at interval
        frame_paths = self._extract_frames(video_path, options.frame_interval_seconds)

        # 3. Tesseract OCR on each frame
        result.ocr_frames = self._ocr_frames(frame_paths)

        # 4. Optional GPT-4o Vision
        if options.enable_visual:
            result.visual_context = self._describe_frames(frame_paths)

        # Cleanup frame files
        for ts, path in frame_paths:
            Path(path).unlink(missing_ok=True)

        result.metadata["frame_count"] = len(frame_paths)
        result.metadata["ocr_frame_count"] = len(result.ocr_frames)
        result.metadata["visual_context_count"] = len(result.visual_context)

        return result

    def _transcribe(self, video_path: str) -> list[TranscriptSegment]:
        """Transcribe video. Uses Groq Whisper if GROQ_API_KEY is set, else Azure OpenAI Whisper."""
        if config.GROQ_API_KEY:
            return self._transcribe_groq(video_path)
        return self._transcribe_azure(video_path)

    def _transcribe_groq(self, video_path: str) -> list[TranscriptSegment]:
        """Transcribe via Groq Whisper (whisper-large-v3-turbo). Fast and free-tier available."""
        from openai import OpenAI

        client = OpenAI(
            api_key=config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

        try:
            with open(video_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as exc:
            if "429" in str(exc) or "timeout" in str(exc).lower():
                raise RetryableError(f"Groq Whisper failed (transient): {exc}") from exc
            raise PermanentError(f"Groq Whisper failed: {exc}") from exc

        return self._parse_whisper_result(result)

    def _transcribe_azure(self, video_path: str) -> list[TranscriptSegment]:
        """Transcribe via Azure OpenAI Whisper. Fallback when Groq is not configured."""
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

        try:
            with open(video_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=config.AZURE_OPENAI_WHISPER_DEPLOYMENT,
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as exc:
            if "429" in str(exc) or "timeout" in str(exc).lower():
                raise RetryableError(f"Whisper transcription failed (transient): {exc}") from exc
            raise PermanentError(f"Whisper transcription failed: {exc}") from exc

        return self._parse_whisper_result(result)

    def _parse_whisper_result(self, result) -> list[TranscriptSegment]:
        """Parse Whisper API response into TranscriptSegments."""

        segments = []
        for seg in getattr(result, "segments", []):
            text = sanitize_text(seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", ""))
            start = seg.get("start", 0.0) if isinstance(seg, dict) else getattr(seg, "start", 0.0)
            end = seg.get("end", 0.0) if isinstance(seg, dict) else getattr(seg, "end", 0.0)
            if text:
                segments.append(TranscriptSegment(text=text, start=start, end=end))

        # Fallback: if no segments but there's a top-level text
        if not segments and hasattr(result, "text") and result.text:
            segments.append(TranscriptSegment(
                text=sanitize_text(result.text), start=0.0, end=0.0
            ))

        return segments

    def _extract_frames(self, video_path: str, interval: float) -> list[tuple[float, str]]:
        """Extract frames every `interval` seconds via ffmpeg. Returns [(timestamp, path)]."""
        # Get duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30,
        )
        try:
            duration = float(probe.stdout.strip())
        except ValueError:
            logger.warning("Could not determine video duration, extracting 0s frame only")
            duration = 0.0

        frame_dir = tempfile.mkdtemp(prefix="bg-frames-")
        frames = []
        ts = 0.0
        while ts <= duration:
            frame_path = os.path.join(frame_dir, f"frame_{ts:.2f}.jpg")
            subprocess.run(
                ["ffmpeg", "-ss", str(ts), "-i", video_path,
                 "-frames:v", "1", "-q:v", "2", frame_path, "-y"],
                capture_output=True, timeout=30,
            )
            if Path(frame_path).exists():
                frames.append((ts, frame_path))
            ts += interval

        return frames

    def _ocr_frames(self, frame_paths: list[tuple[float, str]]) -> list[OcrFrame]:
        """Run Tesseract OCR on extracted frames."""
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract not installed — OCR skipped")
            return []

        results = []
        for ts, path in frame_paths:
            try:
                text = pytesseract.image_to_string(path).strip()
                if text:
                    results.append(OcrFrame(text=sanitize_text(text), timestamp=ts))
            except Exception as exc:
                logger.warning("OCR failed at t=%.2f: %s", ts, exc)

        return results

    def _describe_frames(self, frame_paths: list[tuple[float, str]]) -> list[VisualContext]:
        """Run GPT-4o Vision on extracted frames. Only when enable_visual=True."""
        import base64
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

        results = []
        for ts, path in frame_paths:
            try:
                with open(path, "rb") as img:
                    b64 = base64.b64encode(img.read()).decode()

                response = client.chat.completions.create(
                    model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
                    messages=[
                        {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": "Describe this video advertisement frame."},
                        ]},
                    ],
                    max_tokens=150,
                    temperature=0.1,
                )
                desc = response.choices[0].message.content.strip()
                if desc:
                    results.append(VisualContext(description=desc, timestamp=ts))
            except Exception as exc:
                # ponytail: vision failures are non-fatal — log and continue
                logger.warning("Vision description failed at t=%.2f: %s", ts, exc)

        return results
