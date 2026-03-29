"""
Direct patch example for integrating PMC evaluation into an existing trainer.py.

How to use:
1) Keep `pmc_eval_adapter.py` in same package.
2) Copy the snippets below into your trainer.py and replace placeholder fields.

Placeholders to replace in your project:
- self.passive_encoder  -> your attacked passive representation model
- self.num_classes      -> number of classes
- self.z_dim            -> passive representation dimension
- self.device           -> torch device
"""

from pmc_eval_adapter import PMCEvaluator, PMCEvalConfig


class TrainerPMCMixin:
    """Mixin-style methods you can copy into your Trainer class."""

    def build_pmc_evaluator(self):
        """Call once after trainer/model initialization."""
        cfg = PMCEvalConfig(
            num_classes=self.num_classes,
            feat_dim=self.z_dim,
            epochs=10,
            steps_per_epoch=200,
            lr=2e-3,
            weight_decay=1e-4,
            temperature=0.8,
            lambda_u=1.0,
            use_unlabeled=True,
            topk=5,
            device=str(self.device),
        )
        self.pmc_evaluator = PMCEvaluator(cfg)

    def eval_pmc_attack(
        self,
        pmc_train_labeled_loader,
        pmc_test_loader,
        pmc_train_unlabeled_loader=None,
        use_unlabeled=True,
    ):
        """
        Returns:
            dict: {
              'pmc_top1_acc': float,
              'pmc_top5_acc': float,
              'num_samples': int,
            }
        """
        # If you do not want unlabeled data, force this False.
        self.pmc_evaluator.cfg.use_unlabeled = bool(use_unlabeled)

        metrics = self.pmc_evaluator.run(
            feature_extractor=self.passive_encoder,
            labeled_loader=pmc_train_labeled_loader,
            unlabeled_loader=pmc_train_unlabeled_loader,
            test_loader=pmc_test_loader,
        )
        return metrics


# -----------------------
# Example call site
# -----------------------
# trainer.build_pmc_evaluator()
# pmc_metrics = trainer.eval_pmc_attack(
#     pmc_train_labeled_loader=pmc_train_labeled_loader,
#     pmc_train_unlabeled_loader=pmc_train_unlabeled_loader,  # or None
#     pmc_test_loader=pmc_test_loader,
#     use_unlabeled=True,                                     # False = labeled only
# )
# print('[PMC]', pmc_metrics)
