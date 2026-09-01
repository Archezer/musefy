import os
import torch
import torch.nn as nn
import pytorch_lightning as pl
from sklearn import metrics
from transformers import AutoModelForAudioClassification
import numpy as np

class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=100):
        super().__init__()
        self.encoding = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
        self.encoding[:, 0::2] = torch.sin(position * div_term)
        self.encoding[:, 1::2] = torch.cos(position * div_term)
        self.encoding = self.encoding.unsqueeze(0)  # Shape: (1, max_len, d_model)

    def forward(self, x):
        seq_len = x.size(1)
        return x + self.encoding[:, :seq_len, :].to(x.device)

class FeedforwardModelMTAttnCK(nn.Module):
    def __init__(self, input_size, output_size_classification, output_size_regression, nhead=8, num_layers=1, dropout_rate=0.1, 
                 num_key = 2, num_chords=158, num_chords_root=14, num_chords_attr=14, 
                 key_emb_dim=4, chord_emb_dim=8, chord_root_emb_dim=4, chord_attr_emb_dim=4):
        super().__init__()
        self.d_model = 512

        self.d_model_transformer = chord_root_emb_dim + chord_attr_emb_dim

        # Embedding layers for chords and keys
        self.chord_root_embedding = nn.Embedding(num_chords_root, chord_root_emb_dim)
        self.chord_attr_embedding = nn.Embedding(num_chords_attr, chord_attr_emb_dim)

        nn.init.xavier_uniform_(self.chord_root_embedding.weight)
        nn.init.xavier_uniform_(self.chord_attr_embedding.weight)
        
        # Positional encoding for chord progression
        self.positional_encoding = PositionalEncoding(self.d_model_transformer)

        # Transformer for chord progression modeling
        self.chord_transformer = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(d_model=self.d_model_transformer, nhead=nhead, dim_feedforward= 64, dropout=0.1, batch_first=True),
            num_layers=2
        )
        
        self.input_proj = nn.Sequential(
            nn.Linear(input_size +  self.d_model_transformer + 1, self.d_model),
            nn.ReLU(),
        )

        # Classification branch (e.g., Jamendo - mood classification with 56 classes)
        self.classification_branch = nn.Sequential(
            nn.Linear(self.d_model, 256),
            nn.ReLU(),
            nn.Linear(256, output_size_classification)  # Output: 56 classes
        )
        
        # Regression branch (e.g., DMDD - valence-arousal prediction, including std values)
        self.regression_branch = nn.Sequential(
            nn.Linear(self.d_model, 256),
            nn.ReLU(),
            nn.Linear(256, output_size_regression)  # Output: [mean, std] for valence-arousal
        )


    def forward(self, model_input_dic ):
        x_mert = model_input_dic["x_mert"] 
        x_chord_root = model_input_dic["x_chord_root"]
        x_chord_attr = model_input_dic["x_chord_attr"]

        x_key = model_input_dic["x_key"]
        key_embedding = x_key.float()

        chord_root_embedding = self.chord_root_embedding(x_chord_root)  # Shape: (batch_size, seq_len, chord_root_emb_dim)
        chord_attr_embedding = self.chord_attr_embedding(x_chord_attr)  # Shape: (batch_size, seq_len, chord_attr_emb_dim)
        
        # Concatenate root and attribute embeddings
        chord_combined_embedding = torch.cat(
            (chord_root_embedding, chord_attr_embedding), dim=-1
        )  # Shape: (batch_size, seq_len, chord_root_emb_dim + chord_attr_emb_dim)

        chord_combined_embedding = self.positional_encoding(chord_combined_embedding)
        cls_token = torch.zeros_like(chord_combined_embedding[:, :1, :])

        chord_embedding_with_cls = torch.cat([cls_token, chord_combined_embedding], dim=1)  # Add CLS at the start                
        chord_embedding_transformed = self.chord_transformer(chord_embedding_with_cls)  # Shape: (seq_len+1, batch_size, chord_emb_dim)

        chord_embedding_cls = chord_embedding_transformed[:,0,:]  # Shape: (batch_size, chord_emb_dim)
        
        # Combine all features
        combined_features = torch.cat((x_mert, chord_embedding_cls, key_embedding), dim=1)
        # Input projection
        combined_features = self.input_proj(combined_features)  # Shape: (batch_size, d_model)

        classification_output = self.classification_branch(combined_features)
        regression_output = self.regression_branch(combined_features)
        
        return classification_output, regression_output