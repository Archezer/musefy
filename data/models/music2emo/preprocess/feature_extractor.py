import os
import torch
import torchaudio
import torchaudio.transforms as T
from tqdm import tqdm
import numpy as np
from omegaconf import DictConfig
import hydra
from hydra.utils import to_absolute_path
from transformers import Wav2Vec2FeatureExtractor, AutoModel

from encoder.mert import FeatureExtractorMERT
from encoder.music2latent import FeatureExtractorM2L

class AudioProcessor:
    def __init__(self, cfg: DictConfig):
        self.input_directory = cfg.dataset.input_dir
        self.output_directory = cfg.dataset.output_dir
        self.segment_duration = cfg.segment_duration
        self.resample_rate = cfg.model.sr
        self.device_id = cfg.device_id        
        self.feature_extractor = self._initialize_extractor(cfg.model.name)
        self.is_split = cfg.is_split

    def _initialize_extractor(self, model_name: str):
        if "MERT" in model_name:
            return FeatureExtractorMERT(model_name=model_name, device_id=self.device_id, sr=self.resample_rate)
        elif "music2latent" == model_name:
            return FeatureExtractorM2L(device_id=self.device_id, sr=self.resample_rate)
        else:
            raise NotImplementedError(f"Feature extraction for model {model_name} is not implemented.")

    def resample_waveform(self, waveform, original_sample_rate, target_sample_rate):
        if original_sample_rate != target_sample_rate:
            resampler = T.Resample(original_sample_rate, target_sample_rate)
            return resampler(waveform), target_sample_rate
        return waveform, original_sample_rate

    def split_audio(self, waveform, sample_rate):
        segment_samples = self.segment_duration * sample_rate
        total_samples = waveform.size(0)

        segments = []
        for start in range(0, total_samples, segment_samples):
            end = start + segment_samples
            if end <= total_samples:
                segment = waveform[start:end]
                segments.append(segment)
        
        # In case audio length is shorter than segment length.
        if len(segments) == 0: 
            segment = waveform
            segments.append(segment)

        return segments

    def process_audio_file(self, file_path, output_dir):
        print(f"Processing {file_path}")
        waveform, sample_rate = torchaudio.load(file_path)
        
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0).unsqueeze(0)
        waveform = waveform.squeeze()
        waveform, sample_rate = self.resample_waveform(waveform, sample_rate, self.resample_rate)
        
        if self.is_split:        
            segments = self.split_audio(waveform, sample_rate)
            for i, segment in enumerate(segments):
                segment_save_path = os.path.join(output_dir, f"segment_{i}.npy")
                if os.path.exists(segment_save_path):
                    continue
                self.feature_extractor.extract_features_from_segment(segment, sample_rate, segment_save_path)
        else:
            segment_save_path = os.path.join(output_dir, f"segment_0.npy")
            if not os.path.exists(segment_save_path):
                self.feature_extractor.extract_features_from_segment(waveform, sample_rate, segment_save_path)

    def process_directory(self):
        for root, _, files in os.walk(self.input_directory):
            for file in files:
                if file.endswith('.mp3'):
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, self.input_directory)
                    output_file_dir = os.path.join(self.output_directory, os.path.splitext(relative_path)[0])
                    os.makedirs(output_file_dir, exist_ok=True)
                    self.process_audio_file(file_path, output_file_dir)

@hydra.main(version_base=None, config_path="../config", config_name="prep_config")
def main(cfg: DictConfig):
    processor = AudioProcessor(cfg)
    processor.process_directory()

if __name__ == "__main__":
    main()