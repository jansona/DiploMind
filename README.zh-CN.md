# DiploMind

支持 **多个真人 + AI 混合对局** 的经典《外交》桌游。真人选择国家，AI 补齐剩余席位；公开或私下谈判，在 3D 棋盘上编辑命令，最后由 `diplomacy` 引擎统一裁决。

[English](README.md) · [模型接入说明](docs/PROVIDERS.md) · [Blender 资源说明](docs/ASSETS.md)

![Classic 棋盘、Blender 棋子与命令草稿](docs/screenshots/classic-table.png)

*当前界面的真实 Chromium 截图：两个独立真人席位、五个离线模拟对手。截图展示交互，不代表真实 LLM 的策略水平。*

<details>
<summary>大厅与移动端</summary>

![游戏大厅](docs/screenshots/lobby.png)

<img src="docs/screenshots/mobile-orders.png" alt="移动端棋盘与命令面板" width="360">

</details>

## 无费用本地体验

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。当前重构位于 `dot/cloud-rebuild` 分支，默认分支未被覆盖。

```bash
git clone --branch dot/cloud-rebuild https://github.com/jansona/DiploMind.git
cd DiploMind
uv sync --frozen
DIPLOMIND_CONFIG=conf/mock.json uv run uvicorn diplomind.web:app --host 127.0.0.1 --port 8731
```

打开 `http://127.0.0.1:8731`。

**当前默认对手是离线启发式模拟器，不是真实 LLM。** 无需密钥，不发起模型请求。
真实模型需单独配置服务端 API，或明确启用 CLI 适配器。离线测试只能验证游戏流程与程序策略，不能证明真实 AI 足够聪明、像人或有趣。

1. 房主建房并选择国家，开局前邀请朋友按房间码入座
2. 每位玩家使用独立浏览器/标签页；一个身份只拥有一个席位
3. 房主开局，AI 补齐其余国家
4. 每轮最多暂存三条公开/私聊消息，发出第三条会自动就绪；少于三条也可点击「我已就绪」提前结束发言，等大家齐备后统一投递
5. 点选部队，选择引擎允许的命令；草稿可修改、取消，提交后在裁决前可撤回
6. 大家交齐后同时裁决；撤退与冬季建造/解散也在命令面板完成

## 本轮改进

- 标准地图、移动/支援/海运/撤退/建造规则与 18 中心单独胜利
- Blender 制作的真实 GLB 部队、交互式 3D 棋盘、2D 备用视图、命令路线预览
- 独立席位、私聊视角隔离、观战者仅见公开信息
- 过期回合和重复请求保护；防重复开局；暂停、断线重连与本地草稿恢复
- 房间私有存档保存待投递消息、已提交命令、AI 性格/记忆与原席位身份
- API/Ollama 及实验性 Codex、Claude Code、Qoder 服务端 CLI 适配器
- 不同原则与风险偏好的私有人格、按证据判断的信任、谈判承诺进入下令上下文
- 有预算的上下文取舍；可选的一次战术复核 `order_preflight_review` 仅由服务端配置，默认关闭

记忆、承诺和背叛判断是 Classic 的 AI 基础能力。不会把条约变成强制规则，也没有全知公开信誉分。
**Plus 暂缓开发**，内部预留字段不代表完整第二套玩法。

## 安全与服务边界

模型密钥只在服务端配置；网页不能输入任意命令或访问宿主机文件。支持明确授权的仓库外私有密钥文件引用，密钥不会进入存档或源码包。CLI 契约仍仅以模拟子进程测试，未执行真实已登录 CLI。OpenAI 兼容接入已通过 Aliyun/DeepSeek 的两次有界 1901 年混合席位真实对局及专项复测，但仍有非法命令、协同失误与盘面表述错误。详见 [真实复测](docs/REAL_REPLAY_REVIEW.zh-CN.md)、[战术复核](docs/TACTICAL_REVIEW.zh-CN.md) 和 [接入说明](docs/PROVIDERS.md)。CLI 运行在服务端，不是通往玩家电脑的任意命令桥接器。

席位 token 是身份凭据。保留当前浏览器会话；只有昵称或国家名无法找回丢失的凭据。
邀请仅分享房间码/邀请链接，不分享 token。读档保留原房间和席位并暂停，不会赋予陌生人房主身份。

目前必须使用 **单个 Uvicorn worker**，不能直接多进程横向扩容。正式公网部署前还需 HTTPS、限流、账号/找回流程、备份与共享状态协调等运维工作；本次没有公网部署。

`DIPLOMIND_DATA_DIR` 指定数据目录，默认 `logs`。服务重启后，原 token 可恢复暂停中的棋局，房主确认后继续。
默认不设年份上限；自定义上限在完整年份结束后按幸存者和局处理。全体幸存者一致同意的和局投票仍待实现。

## 测试

```bash
uv run pytest -q
node --test tests/test_frontend*.mjs
# 先启动使用 mock 配置的服务
uv run python scripts/e2e_mixed.py
```

当前实现通过 539 项 Python 测试、21 项前端测试；九项浏览器验收与单独执行的原生浏览器就绪手势测试也已验证。截图使用新建模拟房间，不包含真实凭据或真人私聊。

浏览器脚本使用两个独立的脚本控制真人客户端、五个模拟 AI 和一个观战客户端，验证谈判隐私、命令编辑、重连、提交等待/撤回、存读档、裁决及移动端布局。
截图和结果保存至 `artifacts/e2e/`；浏览器可由 `CHROMIUM_EXECUTABLE` 指定。

AGPLv3；底层引擎/地图和 Three.js 保留各自上游许可。Blender 源文件和导出脚本位于 `assets/blender/`。

## 最新验证记录

- [修复后真实混合对局](docs/REAL_REPLAY_REVIEW.zh-CN.md)
- [上下文取舍真实A/B](docs/CONTEXT_AB_REVIEW.zh-CN.md)
- [下令一致性、个性与思考速度](docs/ORDER_CONSISTENCY_REVIEW.zh-CN.md)
- [有条件的一次战术复核](docs/TACTICAL_REVIEW.zh-CN.md)
- [前端及服务器性能](docs/PERFORMANCE.md)

报告保留失败样例和范围限制；合成测试通过不等于完整对局策略可靠。
