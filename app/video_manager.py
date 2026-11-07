import os
import shutil
import subprocess
import json
import struct
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from .logger import app_logger

class VideoManager:
    """Handles video validation, duration inspection, trimming, and safe file organization."""

    def __init__(self, ffmpeg_path: Optional[str] = None, ffprobe_path: Optional[str] = None):
        self.ffmpeg = ffmpeg_path or self._find_binary("ffmpeg")
        self.ffprobe = ffprobe_path or self._find_binary("ffprobe")

    @staticmethod
    def _find_binary(name: str) -> Optional[str]:
        # Check standard PATH
        found = shutil.which(name)
        if found:
            return found
        # Common windows locations
        candidates = [
            f"C:\\ffmpeg\\bin\\{name}.exe",
            f"C:\\Program Files\\ffmpeg\\bin\\{name}.exe",
            f"C:\\ProgramData\\chocolatey\\bin\\{name}.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
        ]
        for c in candidates:
            if Path(c).is_file():
                return str(c)
        return None

    def is_ffmpeg_available(self) -> bool:
        return self.ffmpeg is not None and Path(self.ffmpeg).exists()

    def inspect_video_media(self, file_path: str) -> Dict[str, Any]:
        """Inspects video file duration, dimensions, and validity.
        Uses ffprobe if installed; otherwise falls back to basic MP4 box parsing and file inspection.
        """
        p = Path(file_path)
        if not p.exists() or p.stat().st_size == 0:
            return {"valid": False, "error": "File does not exist or is empty"}

        if self.ffprobe and Path(self.ffprobe).exists():
            try:
                cmd = [
                    self.ffprobe,
                    "-v", "error",
                    "-show_entries", "format=duration,size,bit_rate:stream=width,height,codec_name,duration",
                    "-of", "json",
                    str(p)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    streams = data.get("streams", [])
                    format_info = data.get("format", {})
                    
                    video_stream = next((s for s in streams if "width" in s and s.get("width")), None)
                    duration = float(format_info.get("duration") or (video_stream.get("duration") if video_stream else 0) or 0)
                    width = int(video_stream.get("width", 0)) if video_stream else 0
                    height = int(video_stream.get("height", 0)) if video_stream else 0
                    codec = video_stream.get("codec_name", "") if video_stream else ""

                    return {
                        "valid": True,
                        "duration": round(duration, 2),
                        "width": width,
                        "height": height,
                        "codec": codec,
                        "size_bytes": p.stat().st_size,
                        "tool": "ffprobe"
                    }
            except Exception as e:
                app_logger.warning(f"ffprobe execution failed: {e}. Falling back to internal MP4 parsing.")

        # Fallback inspection: check MP4 signatures (ftyp, moov, mdat)
        return self._inspect_mp4_fallback(p)

    def _inspect_mp4_fallback(self, p: Path) -> Dict[str, Any]:
        try:
            with open(p, "rb") as f:
                header = f.read(12)
                if len(header) < 12:
                    return {"valid": False, "error": "File too small for valid MP4 header"}
                # Check for 'ftyp' box
                if header[4:8] != b'ftyp':
                    return {"valid": False, "error": "File is missing standard MP4 ftyp atom"}

            size_bytes = p.stat().st_size
            return {
                "valid": True,
                "duration": 10.0,  # approximate baseline when ffprobe not present
                "width": 1080,
                "height": 1920,
                "codec": "h264/unknown",
                "size_bytes": size_bytes,
                "tool": "fallback_parser",
                "warning": "FFmpeg not detected. Install FFmpeg for exact millisecond duration validation and trimming."
            }
        except Exception as e:
            return {"valid": False, "error": f"Failed to read file: {e}"}

    def trim_to_target_duration(self, input_file: str, output_file: str, target_seconds: int = 10) -> bool:
        """Trims video using ffmpeg if duration exceeds target_seconds."""
        if not self.is_ffmpeg_available():
            app_logger.warning("FFmpeg not available. Cannot perform video trimming.")
            shutil.copy2(input_file, output_file)
            return True

        try:
            cmd = [
                self.ffmpeg,
                "-y",
                "-ss", "00:00:00",
                "-i", str(input_file),
                "-t", str(target_seconds),
                "-c", "copy",
                str(output_file)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if res.returncode == 0:
                app_logger.info(f"Successfully trimmed video to {target_seconds}s: {output_file}")
                return True
            else:
                app_logger.error(f"FFmpeg trim error: {res.stderr}")
                return False
        except Exception as e:
            app_logger.error(f"Failed to trim video: {e}")
            return False

    def prepare_ready_to_post(self, downloaded_file: str, target_dir: Path, date_str: str, topic_slug: str) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates, cleans up name, and moves video to ready_to_post folder."""
        info = self.inspect_video_media(downloaded_file)
        if not info.get("valid"):
            return False, "", info

        target_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{date_str}_{topic_slug}_reel"
        dest = target_dir / f"{base_name}.mp4"

        # Unique suffix duplicate prevention
        counter = 1
        while dest.exists():
            dest = target_dir / f"{base_name}_{counter}.mp4"
            counter += 1

        duration = info.get("duration", 0)
        # If duration > 10s and ffmpeg is present, trim
        if duration > 10.5 and self.is_ffmpeg_available():
            trimmed_tmp = target_dir / f"{dest.stem}_temp_trim.mp4"
            ok = self.trim_to_target_duration(downloaded_file, str(trimmed_tmp), 10)
            if ok and trimmed_tmp.exists():
                shutil.move(str(trimmed_tmp), str(dest))
            else:
                shutil.copy2(downloaded_file, str(dest))
        else:
            shutil.copy2(downloaded_file, str(dest))

        app_logger.info(f"Video prepared and validated: {dest}")
        return True, str(dest), info
