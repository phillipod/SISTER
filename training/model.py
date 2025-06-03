import torch
import torch.nn as nn

class CRNN(nn.Module):
    def __init__(self, num_classes: int, input_channels: int = 1):
        super(CRNN, self).__init__()
        
        # CNN layers
        self.cnn = nn.Sequential(
            # Layer 1
            nn.Conv2d(input_channels, 64, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            
            # Layer 2
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            
            # Layer 3
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            
            # Layer 4
            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d((2, 1)),  # Pool only height
            
            # Layer 5
            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            
            # Layer 6
            nn.Conv2d(512, 512, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d((2, 1)),  # Pool only height
            
            # Layer 7
            nn.Conv2d(512, 512, kernel_size=2),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True)
        )
        
        # Calculate output size of CNN
        self.cnn_output_height = 1  # After all the pooling
        self.cnn_output_width = 30  # Depends on input size, this is for 128 width input
        
        # Bidirectional GRU
        self.rnn = nn.GRU(
            input_size=512,
            hidden_size=256,
            num_layers=2,
            bidirectional=True,
            batch_first=True
        )
        
        # Label classifier
        self.label_classifier = nn.Sequential(
            nn.Linear(512, 256),  # 512 = bidirectional GRU with 256 hidden size
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(256, num_classes)
        )
        
        # Platform classifier (binary: PC vs Console)
        self.platform_classifier = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(256, 2)  # 2 classes: PC and Console
        )
        
    def forward(self, x):
        # CNN feature extraction: (batch, channels, height, width)
        conv = self.cnn(x)
        
        # Reshape for RNN: (batch, width, channels)
        b, c, h, w = conv.size()
        conv = conv.squeeze(2)  # Remove height dimension
        conv = conv.permute(0, 2, 1)  # (batch, width, channels)
        
        # RNN sequence processing
        rnn_output, _ = self.rnn(conv)
        
        # Use the last output for classification
        final_output = rnn_output[:, -1]
        
        # Get predictions
        label_logits = self.label_classifier(final_output)
        platform_logits = self.platform_classifier(final_output)
        
        return {
            "label_logits": label_logits,
            "platform_logits": platform_logits
        } 