import os
import argparse
from pathlib import Path
import json
from typing import List, Dict, Tuple

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, random_split
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from dataset import LabeledRegionDataset
from model import CRNN

def train_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion_label: nn.Module,
    criterion_platform: nn.Module,
    optimizer: optim.Optimizer,
    device: torch.device,
    epoch: int,
    writer: SummaryWriter
) -> Tuple[float, float, float]:
    model.train()
    total_loss = 0
    label_correct = 0
    platform_correct = 0
    total = 0
    
    progress = tqdm(loader, desc=f"Training Epoch {epoch}")
    for batch_idx, batch in enumerate(progress):
        images = batch["image"].to(device)
        label_targets = batch["label_idx"].to(device)
        platform_targets = batch["platform_idx"].to(device)
        
        optimizer.zero_grad()
        
        output = model(images)
        label_logits = output["label_logits"]
        platform_logits = output["platform_logits"]
        
        # Calculate losses
        loss_label = criterion_label(label_logits, label_targets)
        loss_platform = criterion_platform(platform_logits, platform_targets)
        loss = loss_label + loss_platform
        
        loss.backward()
        optimizer.step()
        
        total_loss += loss.item()
        
        # Calculate accuracies
        label_pred = label_logits.argmax(dim=1)
        platform_pred = platform_logits.argmax(dim=1)
        
        label_correct += (label_pred == label_targets).sum().item()
        platform_correct += (platform_pred == platform_targets).sum().item()
        total += images.size(0)
        
        # Update progress bar
        progress.set_postfix({
            "loss": f"{loss.item():.4f}",
            "label_acc": f"{100.0 * label_correct / total:.2f}%",
            "platform_acc": f"{100.0 * platform_correct / total:.2f}%"
        })
    
    # Calculate final metrics
    avg_loss = total_loss / len(loader)
    label_accuracy = 100.0 * label_correct / total
    platform_accuracy = 100.0 * platform_correct / total
    
    # Log to tensorboard
    writer.add_scalar("train/loss", avg_loss, epoch)
    writer.add_scalar("train/label_accuracy", label_accuracy, epoch)
    writer.add_scalar("train/platform_accuracy", platform_accuracy, epoch)
    
    return avg_loss, label_accuracy, platform_accuracy

def validate(
    model: nn.Module,
    loader: DataLoader,
    criterion_label: nn.Module,
    criterion_platform: nn.Module,
    device: torch.device,
    epoch: int,
    writer: SummaryWriter
) -> Tuple[float, float, float]:
    model.eval()
    total_loss = 0
    label_correct = 0
    platform_correct = 0
    total = 0
    
    with torch.no_grad():
        for batch in loader:
            images = batch["image"].to(device)
            label_targets = batch["label_idx"].to(device)
            platform_targets = batch["platform_idx"].to(device)
            
            output = model(images)
            label_logits = output["label_logits"]
            platform_logits = output["platform_logits"]
            
            # Calculate losses
            loss_label = criterion_label(label_logits, label_targets)
            loss_platform = criterion_platform(platform_logits, platform_targets)
            loss = loss_label + loss_platform
            
            total_loss += loss.item()
            
            # Calculate accuracies
            label_pred = label_logits.argmax(dim=1)
            platform_pred = platform_logits.argmax(dim=1)
            
            label_correct += (label_pred == label_targets).sum().item()
            platform_correct += (platform_pred == platform_targets).sum().item()
            total += images.size(0)
    
    # Calculate final metrics
    avg_loss = total_loss / len(loader)
    label_accuracy = 100.0 * label_correct / total
    platform_accuracy = 100.0 * platform_correct / total
    
    # Log to tensorboard
    writer.add_scalar("val/loss", avg_loss, epoch)
    writer.add_scalar("val/label_accuracy", label_accuracy, epoch)
    writer.add_scalar("val/platform_accuracy", platform_accuracy, epoch)
    
    return avg_loss, label_accuracy, platform_accuracy

def main():
    parser = argparse.ArgumentParser(description="Train CRNN model on labeled regions")
    parser.add_argument("--data-dirs", nargs="+", required=True, help="List of user label output directories")
    parser.add_argument("--output-dir", default="output", help="Directory to save model checkpoints and logs")
    parser.add_argument("--batch-size", type=int, default=32, help="Training batch size")
    parser.add_argument("--epochs", type=int, default=100, help="Number of epochs to train")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--val-split", type=float, default=0.2, help="Validation split ratio")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu", help="Device to train on")
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize tensorboard writer
    writer = SummaryWriter(output_dir / "logs")
    
    # Load dataset
    dataset = LabeledRegionDataset(args.data_dirs)
    
    # Split dataset
    val_size = int(len(dataset) * args.val_split)
    train_size = len(dataset) - val_size
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size])
    
    # Create data loaders
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=4,
        pin_memory=True
    )
    
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=4,
        pin_memory=True
    )
    
    # Initialize model
    model = CRNN(num_classes=dataset.num_classes)
    model = model.to(args.device)
    
    # Save class mapping
    with open(output_dir / "class_mapping.json", "w") as f:
        json.dump({
            "class_to_idx": dataset.class_to_idx,
            "platform_to_idx": dataset.platform_to_idx
        }, f, indent=2)
    
    # Initialize loss and optimizer
    criterion_label = nn.CrossEntropyLoss()
    criterion_platform = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    
    # Training loop
    best_val_loss = float('inf')
    for epoch in range(args.epochs):
        # Train
        train_loss, train_label_acc, train_platform_acc = train_epoch(
            model, train_loader, criterion_label, criterion_platform,
            optimizer, args.device, epoch, writer
        )
        
        # Validate
        val_loss, val_label_acc, val_platform_acc = validate(
            model, val_loader, criterion_label, criterion_platform,
            args.device, epoch, writer
        )
        
        # Save checkpoint if validation loss improved
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            checkpoint = {
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_loss": val_loss,
                "val_label_acc": val_label_acc,
                "val_platform_acc": val_platform_acc
            }
            torch.save(checkpoint, output_dir / "best_model.pth")
        
        print(f"Epoch {epoch}:")
        print(f"  Train - Loss: {train_loss:.4f}, Label Acc: {train_label_acc:.2f}%, Platform Acc: {train_platform_acc:.2f}%")
        print(f"  Val   - Loss: {val_loss:.4f}, Label Acc: {val_label_acc:.2f}%, Platform Acc: {val_platform_acc:.2f}%")
    
    writer.close()

if __name__ == "__main__":
    main() 