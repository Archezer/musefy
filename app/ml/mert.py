import numpy as np
import torch
import torchaudio
from torch.nn import functional as F
from transformers import (
    AutoModel,
    Wav2Vec2FeatureExtractor,
)

from app.storage.paths import resolve_mert_source

MODEL_NAME = "m-a-p/MERT-v1-95M"
MODEL_SOURCE = resolve_mert_source(MODEL_NAME)


class MertAudioEmbedder:
    def __init__(self, device: str | None = None) -> None:
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(
            MODEL_SOURCE,
            trust_remote_code=True,
        )

        self.model = AutoModel.from_pretrained(
            MODEL_SOURCE,
            trust_remote_code=True,
        ).to(self.device)

        self.model.eval()
        self.sample_rate = self.processor.sampling_rate


    def embed_waveform(
        self,
        waveform: torch.Tensor,
        sample_rate: int,
    ) -> np.ndarray:
        if waveform.ndim == 2:
            waveform = waveform.mean(dim=0)

        if sample_rate != self.sample_rate:
            waveform = torchaudio.functional.resample(
                waveform,
                sample_rate,
                self.sample_rate,
            )

        inputs = self.processor(
            waveform.detach().cpu().numpy(),
            sampling_rate=self.sample_rate,
            return_tensors="pt",
        )

        inputs = {
            name: value.to(self.device)
            for name, value in inputs.items()
        }

        with torch.inference_mode():
            outputs = self.model(
                **inputs,
                output_hidden_states=True,
            )

        hidden_state = outputs.hidden_states[-1]
        embedding = hidden_state.mean(dim=1)
        embedding = F.normalize(embedding, p=2, dim=1)

        return embedding[0].cpu().numpy().astype(np.float32)


        
