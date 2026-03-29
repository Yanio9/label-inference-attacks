# 模型补全攻击（被动 + 主动）与防御代码索引（本仓库）

## 1) 入口脚本与实验脚本

- `Code/run_model_completion.bat`
  - 统一调用 `model_completion.py`（图像/表格）和 `model_completion_mixtext.py`（Yahoo 文本）执行模型补全标签推断。
  - 通过 `--resume-name ..._normal_... / ..._mal_... / ..._mal-all_...` 切换被动/主动攻击实验模型。
- `Code/run_training.bat`
  - 训练 VFL 框架并保存可供模型补全阶段加载的底模检查点；
  - `--use-mal-optim False`（normal）对应被动；`--use-mal-optim True`（mal）和 `--use-mal-optim-all True`（mal-all）对应主动攻击设置。
- `Code/run_training_possible_defense.bat` + `Code/run_mc_possible_defense.bat`
  - 前者训练时启用防御（梯度侧）；后者在这些防御模型上执行模型补全评估。

## 2) 模型补全攻击代码（核心）

- `Code/model_completion.py`
  - 主程序：构造攻击者推断头 `BottomModelPlus`，加载训练好的 VFL 检查点，将其中恶意方底模参数拷入攻击模型；
  - 在少量标注 + 大量无标注上做半监督训练（MixMatch 风格）来恢复标签分类能力；
  - 会在完整训练集/测试集报告标签推断精度。
- `Code/model_completion_mixtext.py`
  - Yahoo 文本任务的模型补全版本，逻辑同上。

## 3) “被动 vs 主动” 在仓库中的对应关系

仓库并没有单独写两个 `passive.py` / `active.py`，而是通过“训练阶段是否使用恶意优化器”来得到不同可攻击模型，再统一用 `model_completion.py` 执行标签推断：

- 被动（Passive）：
  - 训练时 `--use-mal-optim False --use-mal-optim-all False`，得到 `..._normal_...pth` 检查点；
  - 模型补全阶段加载 normal 检查点评估。
- 主动（Active）：
  - 训练时启用恶意优化器 `--use-mal-optim True`（mal）或 `--use-mal-optim-all True`（mal-all）；
  - 恶意优化器实现见 `Code/my_optimizers.py::MaliciousSGD`（对梯度做按历史比值缩放并截断范围），放大可泄露信号后再由模型补全脚本利用。

## 4) 防御代码

- `Code/possible_defenses.py`
  - `dp_gc_ppdl(...)`：PPDL（裁剪 + 选择 + 拉普拉斯扰动）
  - `TensorPruner`：梯度压缩（保留大幅值梯度）
  - `DPLaplacianNoiseApplyer`：加拉普拉斯噪声
  - `multistep_gradient(...)`：多级量化梯度
- `Code/vfl_framework.py`
  - 在每个 batch 中读取 top model 回传给底模的梯度后，按开关调用上述防御函数，最后再下发给各参与方更新。

## 5) 运行顺序建议（最小复现）

1. 先跑 `run_training.bat`（或等价命令）得到 `normal/mal/mal-all` 检查点；
2. 再跑 `run_model_completion.bat`，用不同 `--resume-name` 对比被动/主动攻击效果；
3. 防御实验：先跑 `run_training_possible_defense.bat`，再跑 `run_mc_possible_defense.bat`。

## 6) 代码阅读优先级（建议）

1. `Code/vfl_framework.py`（理解攻击面与防御挂载点）
2. `Code/my_optimizers.py`（理解主动攻击机制）
3. `Code/model_completion.py`（理解标签恢复过程）
4. `Code/possible_defenses.py`（理解防御算子细节）

## 7) 模型补全里“大量无标签数据”来自哪里？

核心结论：**来自同一数据集的训练划分（不是外部新数据）**。

- `model_completion.py` 会调用 `get_datasets_for_ssl(...)` 同时取回 `train_labeled_set` 与 `train_unlabeled_set`。
- 图像/表格等多数数据集（如 CIFAR10）是把原训练集按类别分成两部分：每类前 `n_labeled_per_class` 作为有标签，其余都进入无标签池。
- Criteo 是按索引切片：前 `n_labeled` 条作有标签，后续样本作为无标签（实现中近似按 `1e6 - n_labeled` 取训练样本）。
- Yahoo 文本任务同样从原训练集切分出 labeled / unlabeled / val，`model_completion_mixtext.py` 直接读取该拆分。

因此这里“无标签”主要是**训练集内去标签后的样本**，而不是独立采集的额外语料/图像。

## 8) 你贴的 `eval_privacy_pmc_auc(...)` 与本仓库实现差异（PMC 评估）

你贴的函数思路是：
- 对每个被动方 `k` 收集其输出 `z_k`；
- 训练一个外部 `LogisticRegression` 作为 label predictor；
- 用 `AUC`（二分类/多分类 OVR-macro）度量标签泄露。

而本仓库 `model_completion.py` / `model_completion_mixtext.py` 的思路是：
- 不是“每个被动方单独做线性探针”，而是训练一个攻击模型（`BottomModelPlus` + 半监督训练）进行标签恢复；
- 评估指标默认是 top-1 / top-k accuracy（并在二分类时附加 precision/recall/F1），不是 AUC。

因此二者主要区别在于：
1. **攻击器容量**：LogReg 线性探针 vs. 神经网络推断头 + MixMatch 式半监督训练；
2. **评估目标**：AUC（排序能力） vs. accuracy/top-k（分类命中）；
3. **对象粒度**：你的代码按“每个被动方 k”分别评估，本仓库主要围绕“攻击者一方可见特征 + 训练出的底模表示”做恢复。

是否“合适”取决于你的实验目的：
- 若你要做**轻量、可解释、跨方法统一的泄露基线**，你贴的 AUC 版本很合适；
- 若你要对齐论文/仓库主结果（模型补全攻击），应优先沿用当前仓库流程与 accuracy/top-k 指标；
- 最佳实践是两者都报告：`AUC(LogReg probe)` + `ACC(top-k, model completion)`，分别反映“线性可分泄露”与“强攻击器可利用泄露”。

## 9) BottomModelPlus 到底是“直接加载原底模”还是“单独模型”？

结论：**两者都有**，它是“原底模 + 新推断头”的组合模型。

- 在结构定义里，`BottomModelPlus` 内部先有一个 `self.bottom_model`，然后再接若干全连接层与 `fc_final`（可配 `num_layer/use_bn/activation`）。
- 在模型补全脚本中先实例化 `BottomModelPlus`，随后从 VFL checkpoint 把原训练好的恶意底模参数拷贝到 `model.bottom_model`；新增的推断头层则由模型补全阶段训练。

所以它不是“完全独立于原底模”的新模型，也不是“只用原底模不加头”；而是**以原底模为骨干，再叠加攻击者的标签推断头**。

## 10) 分类头设置了几层？具体配置是什么？

以 `model_completion.py`（图像/表格任务）为准：

- 可配置参数：
  - `--num-layer`：分类头层数，默认 `1`；
  - `--activation_func_type`：`ReLU / Sigmoid / None`；
  - `--use-bn`：是否在各层前使用 BatchNorm。
- 结构实现位于 `BottomModelPlus`：
  - 固定预定义了 `fc_1~fc_4` 和 `fc_final`；
  - 实际启用由 `num_layer` 控制：
    - `num_layer=1`：仅 `bottom_model -> (bn_final/act 可选) -> fc_final`
    - `num_layer=2`：额外启用 `fc_1`
    - `num_layer=3`：额外启用 `fc_1, fc_2`
    - `num_layer=4`：额外启用 `fc_1~fc_3`
    - `num_layer=5`：额外启用 `fc_1~fc_4`

补充：`run_model_completion.bat` 里也确实把 `num-layer` 从 1 到 5 都跑了一遍（用于架构敏感性实验）。

## 11) 模型补全攻击评估指标：ACC 还是 AUC？

本仓库主流程里，**模型补全攻击的核心指标是 ACC（top-1 / top-k accuracy）**，不是 AUC。

- 在 `model_completion.py` 的 `validate(...)` 中，显式计算并输出 `top 1 accuracy` 和 `top k accuracy`；
- 二分类任务会额外打印 `precision / recall / F1`，但仍未使用 AUC 作为主指标；
- `model_completion_mixtext.py` 也是按验证集/测试集准确率（acc）来选择和报告结果。

AUC 只会出现在你前面贴的“外部 LogReg probe”评估范式中，不是这个仓库模型补全主代码默认报告的指标。

## 12) 只用少量有标签数据训练分类头（不使用大量无标签）是否合适？

可以做，但请把它明确标注为**弱化版/受限信息攻击评估**，不要与仓库默认“模型补全（半监督）”主结果直接横比。

原因：
- 本仓库 `model_completion.py` 主流程是“少量有标签 + 大量无标签”的半监督训练（含 pseudo-label/mixup 一致性项）；
- 如果你去掉无标签，仅用少量有标签训练分类头，本质更接近 **few-shot supervised probe**，攻击器能力会显著降低，结果通常更保守。

建议报告方式：
1. 报告 `Few-shot supervised head`（仅 labeled）；
2. 报告 `PMC semi-supervised`（labeled + unlabeled，仓库默认）；
3. 若你还做了 LogReg+AUC probe，可作为第三条“线性泄露下界”。

这样读者能清楚看到：
- 线性可分泄露（AUC probe）
- 少样本监督可利用泄露（few-shot head）
- 半监督强攻击器可利用泄露（PMC 默认）

实操上，如果你坚持只用少量 labeled：
- 保持与默认流程相同的 backbone/checkpoint、同样的数据划分与随机种子；
- 在文中明确写“未使用 unlabeled pool”；
- 评价指标可继续用 ACC/top-k（便于与仓库主指标对照），同时可补充 AUC 作为排序指标。

## 13) 无标签数据的伪标签是如何生成的？

在 `model_completion.py`（图像/表格）里，伪标签生成步骤是：

1. 先用当前模型对无标签输入 `inputs_u` 前向，得到 `outputs_u`；
2. 对 `outputs_u` 做 `softmax` 得到类别概率 `p`；
3. 做温度锐化（temperature sharpening）：`pt = p ** (1 / T)`；
4. 再按类别维归一化：`targets_u = pt / pt.sum(dim=1, keepdim=True)`；
5. `detach()` 后作为伪标签参与后续 mixup 与半监督损失。

直观上：
- `T < 1` 会让分布更“尖锐”（更接近 one-hot），提高伪标签置信度；
- 这些伪标签不是硬标签，而是软标签分布（soft pseudo labels）。

## 14) PMC（模型补全）攻击在本仓库中的完整流程（详细）

下面按“先训练目标底模，再做模型补全攻击”的顺序说明。

### A. 先得到可攻击的底模 checkpoint

1. 先运行 `vfl_framework.py` 训练 VFL（normal / mal / mal-all 三种设定）。
2. 训练结束后会保存整个框架 checkpoint，里面包含恶意方底模 `malicious_bottom_model_a`。
3. 后续 PMC 会加载这个 checkpoint，把恶意方底模拷到攻击模型里。

### B. 构造 PMC 攻击数据（少量标注 + 大量无标注）

1. `model_completion.py` 调用 `get_datasets_for_ssl(...)`，返回：
   - `train_labeled_set`
   - `train_unlabeled_set`
   - `test_set`
   - `train_complete_dataset`
2. 攻击者只保留自己那一半特征（`clip_function(..., args.half)`）。

### C. 构造攻击模型（BottomModelPlus）

1. 新建 `BottomModelPlus`：其结构是 `bottom_model` + 可配置推断头（`fc_1~fc_4 + fc_final`）。
2. 从 VFL checkpoint 载入 `malicious_bottom_model_a`，覆盖到 `model.bottom_model`。
3. 这样攻击模型拥有“受害训练过程学到的底层表示”，再通过新头部完成标签恢复。

### D. 半监督训练核心（PMC 关键）

每个迭代同时取一批 labeled `(inputs_x, targets_x)` 和 unlabeled `inputs_u`：

1. 对 `inputs_u` 前向得到 `outputs_u`；
2. `softmax -> 温度锐化 p^(1/T) -> 归一化` 得到软伪标签 `targets_u`；
3. 将 `inputs_x + inputs_u` 与 `targets_x + targets_u` 拼接；
4. 做 mixup 与 interleave；
5. 计算半监督损失 `Lx + w * Lu` 并更新参数。

这一步本质是在“极少真实标签”条件下，用无标签样本分布把分类头补全出来。

### E. 评估与输出

1. 在 `validate(...)` 中输出 `top-1/top-k accuracy`（二分类额外 precision/recall/F1）。
2. 训练过程中会在完整训练集/测试集上评估，记录最佳攻击精度。

### F. passive / active 在 PMC 阶段如何体现

- PMC 脚本本身基本一致；区别主要来自它加载的 checkpoint：
  - normal checkpoint -> 被动设定；
  - mal / mal-all checkpoint -> 主动设定。
- 也就是“主动性”主要在上游 VFL 训练时注入（恶意优化器），PMC 阶段负责把泄露信号转成可预测标签。

## 15) labeled 很少、unlabeled 很多时，labeled 会不会被反复利用？

会，**会被反复利用**。这是半监督训练里的常见做法。

在 `model_completion.py` 里：
- 训练循环由 `args.val_iteration` 控制，不是按 labeled 集大小一次性跑完就停；
- 当 `labeled_train_iter` 耗尽时，会重新 `iter(labeled_trainloader)`，继续取下一批；
- `unlabeled_train_iter` 也同样会在耗尽后重置。

因此在“小 labeled / 大 unlabeled”设定下，labeled 样本通常会在多个迭代中重复出现，以稳定监督信号；
unlabeled 则提供覆盖更广的数据分布来约束决策边界。

这也解释了为何损失写成 `Lx + w * Lu`：
- `Lx`（来自少量真标签）负责“锚定语义”；
- `Lu`（来自大量无标签伪标签）负责“利用分布信息做补全”。

## 16) 迁移到你自己的 `trainer.py`（例如 Yanio9/ckd）去评估 PMC：实现建议

如果你想把“这里的 PMC 评估”迁到自己的训练框架，建议按下面四步做最小改造。

### Step 1: 先固定被攻击表示（冻结 backbone）

- 从你当前训练流程拿到“被动方可见表示提取器”（可理解为 `bottom_model`）；
- 在 PMC 评估阶段先 `eval()+freeze`，避免主任务训练干扰；
- 只训练新增的 `label head`（即类似 `BottomModelPlus` 的上层头部）。

### Step 2: 准备 PMC 数据划分

构造三份数据：
- `pmc_train_labeled`（少量有标签）
- `pmc_train_unlabeled`（大量无标签，可选）
- `pmc_test`（评估集）

若你不想用无标签，就把 `pmc_train_unlabeled=None`，退化为 few-shot 监督头。

### Step 3: 在 trainer 中新增一个 `run_pmc_eval(...)`

核心逻辑：
1. 用冻结表示提取器得到 `z`；
2. 训练 label head：
   - 有 unlabeled：走 `Lx + w*Lu`（伪标签 + mixup）
   - 无 unlabeled：只用 `Lx`
3. 在 `pmc_test` 上算 `top1/topk`（可附加 AUC）。

可直接用下面伪代码（放进你的 `trainer.py`）：

```python

def run_pmc_eval(self, labeled_loader, unlabeled_loader, test_loader, use_unlabeled=True):
    feat_extractor = self.passive_encoder.eval()
    for p in feat_extractor.parameters():
        p.requires_grad = False

    head = LabelHead(in_dim=self.z_dim, num_classes=self.num_classes).to(self.device)
    opt = torch.optim.Adam(head.parameters(), lr=2e-3)

    for epoch in range(self.pmc_epochs):
        it_l = iter(labeled_loader)
        it_u = iter(unlabeled_loader) if (use_unlabeled and unlabeled_loader is not None) else None

        for _ in range(self.pmc_steps_per_epoch):
            x_l, y_l = next_cycle(it_l, labeled_loader)
            z_l = feat_extractor(x_l)
            logit_l = head(z_l)
            Lx = F.cross_entropy(logit_l, y_l)

            if it_u is not None:
                x_u, _ = next_cycle(it_u, unlabeled_loader)
                with torch.no_grad():
                    z_u = feat_extractor(x_u)
                    q = torch.softmax(head(z_u), dim=1)
                    q = q ** (1.0 / self.T)
                    y_u = q / q.sum(dim=1, keepdim=True)
                # 可选：mixup/interleave
                Lu = soft_ce(head(z_u), y_u)
                loss = Lx + self.lambda_u * Lu
            else:
                loss = Lx

            opt.zero_grad(); loss.backward(); opt.step()

    return eval_topk(head, feat_extractor, test_loader, k=self.k)
```

### Step 4: 报告建议（避免口径混淆）

至少分两行报告：
- `PMC-supervised-head`（仅 labeled）
- `PMC-semi-supervised`（labeled + unlabeled）

若再加 LogReg probe，请单独写 `Probe-AUC`，不要与 PMC-ACC 混在一个指标里。

## 17) 可直接复制的代码位置

我在本仓库新增了 `Code/pmc_eval_adapter.py`，包含：
- `PMCEvalConfig`
- `PMCEvaluator.run(...)`
- `PMCEvaluator.eval_acc(...)`
- 末尾附带最小接入示例（注释）。

你可以直接把这个文件复制到 `Yanio9/ckd` 仓库，然后在 `trainer.py` 中：
1. 初始化 `PMCEvaluator`；
2. 传入你当前被动方表示提取器（例如 `self.passive_encoder`）；
3. 传入 `pmc_train_labeled_loader / pmc_train_unlabeled_loader / pmc_test_loader`；
4. 读取返回的 `pmc_top1_acc` 和 `pmc_top{k}_acc` 作为评估指标。

## 18) 直接可粘贴到 trainer.py 的补丁示例

新增文件 `Code/pmc_ckd_trainer_patch_example.py` 给出 Mixin 风格方法：
- `build_pmc_evaluator()`
- `eval_pmc_attack(...)`

你只需替换 4 个占位字段：
- `self.passive_encoder`
- `self.num_classes`
- `self.z_dim`
- `self.device`

然后在训练/评估主流程中调用：
1. `trainer.build_pmc_evaluator()`
2. `trainer.eval_pmc_attack(...)`

该示例默认输出 ACC 指标（`pmc_top1_acc`, `pmc_top{k}_acc`）。

## 19) 这里（PMC 评估适配器）里 labeled / unlabeled 数据来源是什么？

分两层理解：

### A. 在本仓库原始 PMC 实现里

- 来源都是同一任务数据集的训练划分：
  - `train_labeled_set`：少量带真标签样本；
  - `train_unlabeled_set`：训练集其余样本（训练时不使用其真标签，只用于伪标签/一致性项）。
- 二者由 `get_datasets_for_ssl(...)` 统一返回。

### B. 在你接入 `pmc_eval_adapter.py` 时

- 适配器**不自己生成数据**，而是完全使用你传入的 DataLoader：
  - `labeled_loader`：你在 `trainer.py` 外部构造的“少量有标签”集合；
  - `unlabeled_loader`：你外部构造的“无标签”集合（可为 `None`）；
  - `test_loader`：你外部构造的评估集。
- 也就是说，来源由你的项目数据管线决定：
  - 若你按原论文口径复现，通常从同一训练集切分 labeled / unlabeled；
  - 若你只想 few-shot 评估，可只传 `labeled_loader` 并令 `use_unlabeled=False`。

推荐最稳妥的数据口径：
1. 从训练集随机抽少量样本作 `labeled_loader`（保留标签）；
2. 训练集剩余样本作 `unlabeled_loader`（训练时不读标签）；
3. 独立测试集作 `test_loader`。

## 20) 训练分类头时是否冻结底部模型参数？

是，默认会冻结。

在 `pmc_eval_adapter.py` 的 `PMCEvaluator.run(...)` 中：
- 先对 `feature_extractor` 执行 `eval()`；
- 然后把其所有参数 `p.requires_grad = False`；
- 优化器只接收 `head.parameters()`。

因此在该适配器实现里，更新的是分类头（`LabelHead`），而不是底部模型（被动方表示提取器）。

## 21) 有标签样本和伪标签样本是否统一成“分布形式”再训练？

分两种实现：

### A. 本仓库原始 `model_completion.py`

是的，**会统一成分布形式**：
- `targets_x` 先被转为 one-hot 分布；
- `targets_u` 是由伪标签得到的软分布；
- 二者拼接后做 mixup，再进入 `Lx/Lu`。

### B. 新增的 `pmc_eval_adapter.py`

不是完全统一成同一形式：
- `Lx` 使用 `F.cross_entropy(logit_l, y_l.long())`（有标签仍是硬标签索引）；
- `Lu` 才使用软伪标签分布做 soft CE。

也就是说：
- 原始 PMC 实现：`targets_x + targets_u` 都可视作分布后再混合；
- 适配器实现：监督分支用硬标签 CE，无监督分支用软标签 CE。

## 22) 这里的 loss 是如何计算的？

按你现在接入的 `pmc_eval_adapter.py` 来看，训练 loss 分两支：

### 1) 有标签分支（监督）

- `loss_x = F.cross_entropy(logit_l, y_l.long())`
- 即标准多类交叉熵：
  \[
  L_x = -\frac{1}{B}\sum_i \log p(y_i\mid x_i)
  \]

### 2) 无标签分支（半监督，可选）

- 先构造软伪标签：
  - `q = softmax(head(z_u))`
  - `q <- q^(1/T)`
  - `y_u = q / sum(q)`
- 再计算 soft CE：
  - `loss_u = -mean(sum(y_u * log_softmax(logits_u)))`

对应公式：
\[
L_u = -\frac{1}{B_u}\sum_i \sum_c \tilde{y}_{ic}\log p_{ic}
\]

### 3) 总损失

- 若有 unlabeled：`loss = loss_x + lambda_u * loss_u`
- 若无 unlabeled：`loss = loss_x`

所以你可以把它理解成：
- `Lx` 由真标签提供“锚点”；
- `Lu` 用伪标签分布提供一致性约束；
- `lambda_u` 控制两者权重。

## 23) 本仓库原始 PMC（`model_completion.py`）的 loss 具体怎么算？

你问“现在这个仓库中”时，如果指原始 PMC 主实现（不是新增适配器），对应是：

1. `SemiLoss.__call__` 里先算两项：
   - `Lx = -mean(sum(log_softmax(outputs_x) * targets_x))`
   - `Lu = mean((softmax(outputs_u) - targets_u)^2)`（MSE 形式）
2. 返回的第三项是权重系数：`w = lambda_u * linear_rampup(epoch)`
3. 训练循环里总损失是：`loss = Lx + w * Lu`

所以原始 PMC 的 `Lu` 不是 soft CE，而是“预测分布 vs 伪标签分布”的均方误差；并且 `Lu` 权重会随 epoch 线性增大（ramp-up）。

## 24) 把 `Lu` 从 MSE 改成 soft CE，效果会差很多吗？

结论：**可能会有明显差异，但方向不一定固定，取决于数据集/温度/权重。**

一般经验（在伪标签训练里常见）：
- soft CE 往往梯度更“尖锐”，当伪标签较准时，收敛更快、上限可能更高；
- 但当伪标签噪声较大时，soft CE 更容易把错误放大，导致不稳定；
- MSE 通常更“平滑/保守”，对噪声鲁棒些，但有时上限略低。

因此你现在的适配器（soft CE）与原始仓库（MSE）不完全同口径，建议做一个小型消融再下结论：

1. 固定同一 backbone/checkpoint 与数据划分；
2. 只改 `Lu` 形式（MSE vs soft CE）；
3. 扫 `temperature`（如 0.5/0.8/1.0）和 `lambda_u`（如 0.5/1/2）；
4. 报告 `pmc_top1_acc / topk_acc` 的均值±方差（多 seed）。

如果你的目标是“严格对齐本仓库原始 PMC 结果”，建议优先用 MSE 版 `Lu`；
如果你的目标是“在自己任务上拿更高攻击精度”，soft CE 值得尝试，但要配合温度与权重调参。

## 25) 这个仓库里训练分类头（PMC）的 epoch 一般设多少？

看两层口径：

### A. 原始 `model_completion.py`（仓库主实现）

- 参数默认值：`--epochs` 默认是 `10`；
- 但批处理脚本里常用设置会按数据集改：
  - Criteo 常见 `5`；
  - CIFAR/CINIC/TinyImageNet 常见 `25`；
  - BC_IDC 常见 `10`。

所以“常见值”不是单一数字，而是 **5 / 10 / 25**（按数据集规模与任务难度调整）。

### B. 新增适配器（`pmc_eval_adapter.py`）

- `PMCEvalConfig` 默认 `epochs=20`；
- 但 `pmc_ckd_trainer_patch_example.py` 的示例里给的是 `epochs=10`，方便先跑通。
