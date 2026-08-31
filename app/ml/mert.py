import torch
from transformers import (
    AutoModel,
    Wav2Vec2FeatureExtractor,
)

MODEL_NAME = "m-a-p/MERT-v1-95M"


class MertAudioEmbedder:
    def __init__(self, device: str | None = None) -> None:
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
        )

        self.model = AutoModel.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
        ).to(self.device)

        self.model.eval()
        self.sample_rate = self.processor.sampling_rate


        
