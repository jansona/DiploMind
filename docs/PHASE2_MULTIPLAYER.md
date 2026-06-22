# 二期 — 多人模式（方案 B：单服多局 + 房间码 + SSE）

> 局域网/朋友直连。2-7 真人任意 + AI 补满 7 国。房间码+昵称认领座位，seat-token 续座。
> 升级 SSE 推送。每局有 owner，可存盘续玩/暂停/结束。谈判轮计时仅对人类生效。

## 决策（已定）
- 网络：同 LAN/朋友直连，无账号。
- 座位：2-7 人任意，空座 AI 补满。
- 身份：房间码 + 昵称 + 座位(国) + seat-token(localStorage)。
- 同步：SSE（服务器单向推），动作仍走 POST。
- 多房：`rooms{code}` 一服多局，不做花哨大厅（建房给码/输码进房）。
- 计时：默认 180s/轮，仅人类，可局内调；owner 可整体开关。
- 超时/掉线：本轮算跳过(谈判)或 hold(下令)；需撤退→解散，需解散→随机解散；
  之后该员超时缩为 30s；任一响应后恢复 180s。掉线≠转 AI，靠超时兜底，同 token 重连回座。

## 数据模型
```
S = {"rooms": {code: Room}}                 # 全局单局 → 多房
Room: code,name,owner_token,status,timer    # status: lobby/playing/paused/ended
      session:Session, seats:{power:{name,token,kind:human|ai}}, timeout_short:set(power)
Session: humans[] 已有 → 收口 say(power)/submit(power)/state(power); token→座位路由
```

## 补充能力
- 掉线/超时兜底（见上），同 token 重连夺座。
- 空座 AI 补满 + 凑齐后 owner 开局。
- 观战席：链接进来可纯看（human=None 基础已在）。
- owner 暂停(冻结计时+拒动作)/结束/转让；闲置房 N 分钟回收。
- 邀请链接 `/?join=CODE`。

## 分步施工（每步绿了再下一步）
1. **座位去单human化** session.py：say/submit/state 带 power，多 human 等齐推进；超时落子规则。
2. **房间注册** rooms{code}、建房/进房、token→(room,seat)，owner=建者。无大厅可玩。
3. **大厅+管理** 主页列房(名/年/座位/状态)、新建/续档/删；owner 暂停/结束/转让。
4. **身份续座** token 存 localStorage，名+房回座；save/load 存座位映射。
5. **SSE 推送** /api/stream/{code} 替 2s 轮询。
6. **计时器** 谈判倒计时(仅人类)、超时落子、邀请链接、缩短/恢复。

## 不做（避免范围蔓延）
账号系统、公网部署、WebSocket 双向、大厅排行——超出 LAN 自用。
