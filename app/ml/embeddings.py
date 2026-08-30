from pathlib import Path
from typing import Protocol

import numpy as np


class AudioEmbedder(Protocol):
    """Converts an audio file into a numeric feature vector."""

    def embed(self, audio_path: Path) -> np.ndarray:
        """Return one embedding vector for the audio file."""
        ...