"""
PMC evaluator adapter.

Usage goal:
- Drop this file into your project (or copy functions into trainer.py).
- Reuse your trained passive encoder as frozen feature extractor.
- Train a small head with labeled-only or semi-supervised (with unlabeled) data.
- Report ACC / Top-k ACC on test set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


TensorPair = Tuple[torch.Tensor, torch.Tensor]


def _next_cycle(it, loader):
    try:
        return next(it), it
    except StopIteration:
        it = iter(loader)
        return next(it), it


@dataclass
class PMCEvalConfig:
    num_classes: int
    feat_dim: int
    epochs: int = 20
    steps_per_epoch: int = 200
    batch_size: int = 64
    lr: float = 2e-3
    weight_decay: float = 1e-4
    temperature: float = 0.8
    lambda_u: float = 1.0
    use_unlabeled: bool = True
    topk: int = 5
    device: str = "cuda"


class LabelHead(nn.Module):
    """Simple head for PMC attack evaluation (supervised or semi-supervised)."""

    def __init__(self, feat_dim: int, num_classes: int):
        super().__init__()
        self.fc = nn.Linear(feat_dim, num_classes)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.fc(z)


class PMCEvaluator:
    """
    Generic PMC evaluator.

    You need to provide:
    - feature_extractor(x): returns passive representation z with shape [B, feat_dim]
    - labeled_loader: yields (x, y)
    - test_loader: yields (x, y)
    - unlabeled_loader (optional): yields (x, _) or x
    """

    def __init__(self, cfg: PMCEvalConfig):
        self.cfg = cfg
        self.device = torch.device(cfg.device if torch.cuda.is_available() else "cpu")

    def _to_xy(self, batch) -> TensorPair:
        if isinstance(batch, (list, tuple)) and len(batch) >= 2:
            x, y = batch[0], batch[1]
        else:
            raise ValueError("Batch must be tuple/list with at least (x, y).")
        return x.to(self.device), y.to(self.device)

    def _to_x(self, batch) -> torch.Tensor:
        if isinstance(batch, (list, tuple)):
            x = batch[0]
        else:
            x = batch
        return x.to(self.device)

    @torch.no_grad()
    def _extract(self, feature_extractor: nn.Module, x: torch.Tensor) -> torch.Tensor:
        z = feature_extractor(x)
        if isinstance(z, (list, tuple)):
            z = z[0]
        return z

    def run(
        self,
        feature_extractor: nn.Module,
        labeled_loader: Iterable,
        test_loader: Iterable,
        unlabeled_loader: Optional[Iterable] = None,
    ) -> dict:
        """
        Returns dict with top1/topk acc.
        """
        cfg = self.cfg

        feature_extractor = feature_extractor.to(self.device)
        feature_extractor.eval()
        for p in feature_extractor.parameters():
            p.requires_grad = False

        head = LabelHead(cfg.feat_dim, cfg.num_classes).to(self.device)
        optimizer = torch.optim.AdamW(
            head.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay
        )

        for _ in range(cfg.epochs):
            head.train()
            it_l = iter(labeled_loader)
            it_u = iter(unlabeled_loader) if (cfg.use_unlabeled and unlabeled_loader is not None) else None

            for _ in range(cfg.steps_per_epoch):
                batch_l, it_l = _next_cycle(it_l, labeled_loader)
                x_l, y_l = self._to_xy(batch_l)

                with torch.no_grad():
                    z_l = self._extract(feature_extractor, x_l)
                logit_l = head(z_l)
                loss_x = F.cross_entropy(logit_l, y_l.long())

                if it_u is not None:
                    batch_u, it_u = _next_cycle(it_u, unlabeled_loader)
                    x_u = self._to_x(batch_u)
                    with torch.no_grad():
                        z_u = self._extract(feature_extractor, x_u)
                        q = torch.softmax(head(z_u), dim=1)
                        q = q ** (1.0 / cfg.temperature)
                        y_u = q / q.sum(dim=1, keepdim=True)

                    logits_u = head(z_u)
                    loss_u = -torch.mean(torch.sum(y_u * F.log_softmax(logits_u, dim=1), dim=1))
                    loss = loss_x + cfg.lambda_u * loss_u
                else:
                    loss = loss_x

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

        metrics = self.eval_acc(feature_extractor, head, test_loader, cfg.topk)
        return metrics

    @torch.no_grad()
    def eval_acc(
        self,
        feature_extractor: nn.Module,
        head: nn.Module,
        test_loader: Iterable,
        topk: int,
    ) -> dict:
        feature_extractor.eval()
        head.eval()

        correct_top1 = 0.0
        correct_topk = 0.0
        total = 0

        for batch in test_loader:
            x, y = self._to_xy(batch)
            z = self._extract(feature_extractor, x)
            logits = head(z)

            k = min(topk, logits.shape[1])
            pred_top1 = torch.argmax(logits, dim=1)
            correct_top1 += (pred_top1 == y.long()).sum().item()

            _, pred_k = torch.topk(logits, k=k, dim=1)
            y_expand = y.view(-1, 1).long()
            correct_topk += (pred_k == y_expand).any(dim=1).sum().item()
            total += y.shape[0]

        return {
            "pmc_top1_acc": correct_top1 / max(total, 1),
            f"pmc_top{topk}_acc": correct_topk / max(total, 1),
            "num_samples": total,
        }


# ---------------------------
# Minimal integration example
# ---------------------------
# cfg = PMCEvalConfig(num_classes=10, feat_dim=128, epochs=10, steps_per_epoch=200)
# evaluator = PMCEvaluator(cfg)
# metrics = evaluator.run(
#     feature_extractor=self.passive_encoder,
#     labeled_loader=pmc_train_labeled_loader,
#     unlabeled_loader=pmc_train_unlabeled_loader,   # or None
#     test_loader=pmc_test_loader,
# )
# print(metrics)
