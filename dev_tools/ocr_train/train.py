# -*- coding: utf-8 -*-
"""Train a dedicated Chaos Zero Traditional Chinese OCR model and export ONNX.

Uses `cnocr`'s `densenet_lite_136-gru` architecture (`OcrModel`) with a clean
UTF-8 DataLoader on CUDA, saves the best checkpoint, and exports a self-contained
ONNX model (opset 14, vocab embedded in metadata) compatible with `toolkit`'s
`onnxruntime==1.14.1`.

Usage:
    .venv_ocr\\Scripts\\python.exe -m dev_tools.ocr_train.train --epochs 20 --batch-size 64
"""

import argparse
import os
import random
import time

import cv2
import numpy as np
import onnx
import torch
from torch.utils.data import DataLoader, Dataset

from cnocr.models.ocr_model import OcrModel
from cnocr.utils import pad_img_seq, read_charset, resize_img

WORK = os.path.join(os.path.dirname(__file__), 'work')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def read_tsv_utf8(tsv_path, img_root):
    items = []
    with open(tsv_path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if '\t' not in line:
                continue
            rel, tok_str = line.split('\t', 1)
            tokens = tok_str.split(' ')
            items.append((os.path.join(img_root, rel), tokens))
    return items


class LineDataset(Dataset):
    def __init__(self, items, augment=False):
        self.items = items
        self.augment = augment

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        path, tokens = self.items[idx]
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            img = np.zeros((32, 64), dtype=np.uint8)

        if self.augment:
            # Slight horizontal stretch
            if random.random() < 0.4:
                ratio = random.uniform(0.88, 1.12)
                new_w = max(8, int(round(img.shape[1] * ratio)))
                img = cv2.resize(img, (new_w, img.shape[0]), interpolation=cv2.INTER_LINEAR)
            # Brightness / contrast jitter
            if random.random() < 0.5:
                alpha = random.uniform(0.85, 1.15)
                beta = random.uniform(-14, 14)
                img = np.clip(img.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)
            # Slight Gaussian noise
            if random.random() < 0.25:
                noise = np.random.normal(0, random.uniform(2, 6), img.shape).astype(np.float32)
                img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
            # Random fg/bg invert with low prob (already represented in dataset)
            if random.random() < 0.10:
                img = 255 - img

        # [1, H, W] -> resize to H=32, normalize [0, 1]
        arr = np.expand_dims(img, axis=0)
        tensor = resize_img(arr, min_width=16, return_torch=True).to(torch.float32) / 255.0
        return tensor, tokens


def collate_fn(batch):
    imgs = [item[0] for item in batch]
    labels = [item[1] for item in batch]
    img_lengths = torch.tensor([img.shape[2] for img in imgs], dtype=torch.long)
    padded = pad_img_seq(imgs, padding_value=0.0)
    label_lengths = torch.tensor([len(lbl) for lbl in labels], dtype=torch.long)
    return padded, img_lengths, labels, label_lengths


def edit_distance(a, b):
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def try_load_pretrained_backbone(model, model_name):
    """Attempt to initialize encoder+decoder from official cnocr pretrained weights."""
    try:
        from cnocr.recognizer import Recognizer
        rec = Recognizer(model_name=model_name, model_backend='pytorch', context='cpu')
        src_sd = rec._model.state_dict()
        dst_sd = model.state_dict()
        loaded = 0
        for k, v in src_sd.items():
            if k.startswith('linear.'):
                continue
            if k in dst_sd and dst_sd[k].shape == v.shape:
                dst_sd[k] = v
                loaded += 1
        model.load_state_dict(dst_sd)
        print(f'Loaded {loaded} pretrained encoder/decoder tensors from {model_name}')
        return loaded > 0
    except Exception as exc:
        print(f'Skipping pretrained backbone ({exc}); training from Kaiming init')
        return False


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    total_loss = 0.0
    n_batches = 0
    exact_ok = 0
    total_lines = 0
    total_edits = 0
    total_chars = 0
    for imgs, img_lengths, labels, _ in loader:
        imgs = imgs.to(device, non_blocking=True)
        img_lengths = img_lengths.to(device, non_blocking=True)
        out = model(imgs, img_lengths, target=labels, return_logits=False, return_preds=True)
        total_loss += out['loss'].item()
        n_batches += 1
        for (pred_tokens, _), gt_tokens in zip(out['preds'], labels):
            p = ''.join(pred_tokens)
            g = ''.join(gt_tokens)
            if p == g:
                exact_ok += 1
            total_lines += 1
            total_edits += edit_distance(p, g)
            total_chars += max(1, len(g))
    char_acc = 1.0 - (total_edits / max(1, total_chars))
    line_acc = exact_ok / max(1, total_lines)
    return total_loss / max(1, n_batches), char_acc, line_acc


def export_onnx(model, vocab, out_path):
    model_cpu = model.to('cpu').eval()
    orig_post = model_cpu.postprocessor
    model_cpu.postprocessor = None
    x = torch.randn(1, 1, 32, 280)
    input_lengths = torch.tensor([280], dtype=torch.long)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with torch.no_grad():
        torch.onnx.export(
            model_cpu,
            args=(x, input_lengths),
            f=out_path,
            export_params=True,
            opset_version=14,
            do_constant_folding=True,
            dynamo=False,
            input_names=['x', 'input_lengths'],
            output_names=['logits', 'output_lengths'],
            dynamic_axes={
                'x': {0: 'batch_size', 3: 'width'},
                'input_lengths': {0: 'batch_size'},
                'logits': {0: 'batch_size', 1: 'seq_len'},
                'output_lengths': {0: 'batch_size'},
            },
        )
    model_cpu.postprocessor = orig_post

    onnx_model = onnx.load(out_path)
    meta = onnx_model.metadata_props.add()
    meta.key = 'character'
    meta.value = '\n'.join(vocab)
    meta2 = onnx_model.metadata_props.add()
    meta2.key = 'preprocess'
    meta2.value = 'cnocr_gray_32_01'
    onnx.checker.check_model(onnx_model)
    onnx.save(onnx_model, out_path)
    print(f'Exported self-contained ONNX ({len(vocab)} chars) -> {out_path}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-name', default='densenet_lite_136-gru')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--lr', type=float, default=2e-3)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--no-pretrained', action='store_true')
    parser.add_argument('--resume-weights', default=None)
    parser.add_argument('--ckpt-name', default='best.pt')
    parser.add_argument('--out-onnx', default=os.path.join(ROOT, 'bin', 'ocr_models', 'chaoszero_cht_rec.onnx'))
    args = parser.parse_args()

    vocab_fp = os.path.join(WORK, 'vocab.txt')
    ds_dir = os.path.join(WORK, 'dataset')
    ckpt_dir = os.path.join(WORK, 'checkpoints')
    os.makedirs(ckpt_dir, exist_ok=True)

    vocab, _ = read_charset(vocab_fp)
    print(f'Vocab size: {len(vocab)} (CTC classes: {len(vocab) + 1})')

    train_items = read_tsv_utf8(os.path.join(ds_dir, 'train.tsv'), ds_dir)
    val_items = read_tsv_utf8(os.path.join(ds_dir, 'dev.tsv'), ds_dir)
    print(f'Dataset: {len(train_items)} train / {len(val_items)} val')

    train_loader = DataLoader(
        LineDataset(train_items, augment=True),
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.workers,
        pin_memory=True,
        collate_fn=collate_fn,
        persistent_workers=args.workers > 0,
    )
    val_loader = DataLoader(
        LineDataset(val_items, augment=False),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.workers,
        pin_memory=True,
        collate_fn=collate_fn,
        persistent_workers=args.workers > 0,
    )

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'Training {args.model_name} on {device}')

    model = OcrModel.from_name(args.model_name, vocab)
    has_pretrained = False
    if args.resume_weights and os.path.exists(args.resume_weights):
        prev = torch.load(args.resume_weights, map_location='cpu', weights_only=False)
        model.load_state_dict(prev['state_dict'])
        print(f'Resumed full weights from {args.resume_weights} (epoch {prev.get("epoch")})')
    elif not args.no_pretrained:
        has_pretrained = try_load_pretrained_backbone(model, args.model_name)
    model = model.to(device)

    if has_pretrained:
        param_groups = [
            {'params': model.encoder.parameters(), 'lr': args.lr * 0.3},
            {'params': model.decoder.parameters(), 'lr': args.lr * 0.6},
            {'params': model.linear.parameters(), 'lr': args.lr * 2.0},
        ]
        optimizer = torch.optim.AdamW(param_groups, weight_decay=1e-4)
        max_lr = [args.lr * 0.3, args.lr * 0.6, args.lr * 2.0]
    else:
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        max_lr = args.lr

    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=max_lr,
        epochs=args.epochs,
        steps_per_epoch=len(train_loader),
        pct_start=0.15,
    )

    best_score = -1.0
    best_ckpt = os.path.join(ckpt_dir, args.ckpt_name)

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        model.train()
        train_loss = 0.0
        for step, (imgs, img_lengths, labels, _) in enumerate(train_loader, 1):
            imgs = imgs.to(device, non_blocking=True)
            img_lengths = img_lengths.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            out = model(imgs, img_lengths, target=labels, return_logits=False, return_preds=False)
            loss = out['loss']
            if torch.isnan(loss) or torch.isinf(loss):
                continue
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            scheduler.step()
            train_loss += loss.item()
            if step % 200 == 0 or step == len(train_loader):
                print(f'  Epoch {epoch:02d} step {step}/{len(train_loader)} loss={train_loss / step:.4f}')

        val_loss, char_acc, line_acc = evaluate(model, val_loader, device)
        dt = time.time() - t0
        print(
            f'Epoch {epoch:02d}/{args.epochs:02d} ({dt:.1f}s) '
            f'| train_loss={train_loss / len(train_loader):.4f} '
            f'| val_loss={val_loss:.4f} '
            f'| char_acc={char_acc:.4f} '
            f'| line_acc={line_acc:.4f}'
        )
        score = 0.7 * line_acc + 0.3 * char_acc
        if epoch == 1 or score > best_score:
            best_score = max(best_score, score)
            torch.save({'state_dict': model.state_dict(), 'vocab': vocab, 'epoch': epoch}, best_ckpt)

    ckpt = torch.load(best_ckpt, map_location='cpu')
    model.load_state_dict(ckpt['state_dict'])
    print(f'Loaded best checkpoint (epoch {ckpt["epoch"]}, score={best_score:.4f})')
    export_onnx(model, vocab, args.out_onnx)


if __name__ == '__main__':
    main()
