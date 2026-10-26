# fallbackchain

**把模型降级与回退策略写成可验证的规则。**

`fallbackchain` —— 描述多级回退策略，验证每级的触发条件、输出契约与终止条件。

- 零依赖，Python 3.10+ 标准库即可运行
- 单文件，`fallbackchain.py` 拷走就能用
- 不联网、不写文件

<!-- ipos:install -->
## 安装

零依赖，Python 3.10+ 即可：

```bash
pip install ijynihanu-fallbackchain
```

装完直接用命令名调用：

```bash
fallbackchain --help
```

也可以不用安装，直接把 `fallbackchain.py` 拷走用——它只依赖标准库。

## 为什么需要它

回退策略多写在文档里；fallbackchain 验证各级的输出契约是否一致，让降级不产生半成品。

它遵守下面几条自己定的规矩：

1. **降级可以，输出契约不能变**。切换到备用模型时，下游还得能用。
2. **验证策略本身**，不执行调用。每级的触发条件、输出契约、终止条件都要对得上。
3. **终止条件必须存在**。没有终止条件的回退链就是无限循环。

## 用法

```bash
python fallbackchain.py --policy policy.json
python fallbackchain.py --policy policy.json --json
```

加 `--json` 可以拿到机器可读的结果，便于接到流水线里。

## 已知局限

- 降级链只按配置顺序执行，不判断语义质量。
- 不接真实模型，只做链路设计与演练。
- 成本估算基于配置里的单价，与实际账单可能有出入。

## 跑测试

```bash
python test_fallbackchain.py
```

测试用独立的断言与临时数据，不污染工作目录。

## 来源与参考

- Python 标准库文档：<https://docs.python.org/3/>
- GitHub 仓库：<https://github.com/ijynihanu/fallbackchain>

---

## 关于作者

ijynihanu 做模型回退策略的契约校验相关的问题。这个工具先替你回答一个具体问题，再谈别的。

- 个人主页：<https://ijynihanu.github.io>
- 仓库：<https://github.com/ijynihanu/fallbackchain>

## 许可

MIT，见 [LICENSE](LICENSE)。
