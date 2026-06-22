# DiploMind 一期归档（2026-06，分支 main）

LLM 单机《外交》：1人+6AI / 混合 / 全AI观战。一期=单机可玩、机制完整、测试齐全。后续开新会话续。

## 已实现
- **引擎**：复用 diplomacy，地图/合法走子/冲突裁决(bounce)/撤退造兵/判胜负(18中心/存活和局)/存档；非法即 hold。
- **玩家对等**：人/AI 共用 Player.negotiate/decide，仅输入源不同；0/1/多人任意国；轮次同步、每轮≤3条、满N轮或全静默转下令。
- **AI 五步**(异步并发)：感知(全单位+上回合命令言行对照)→态度→意图→谈判→下令；性格5参数硬化进prompt；计划性背刺(move_turn)；抢盟友中心=背叛+信任暴跌记仇。
- **记忆**：关系/承诺(到期)/背叛戳/diary滚动摘要；只读纪律(消息不改他人记忆)。
- **网关**：任意 OpenAI 兼容 API(ollama默认)；JSON宽松解析+并发闸+超时容错+num_predict。
- **Web**：主菜单(新局选国/语言/预设·继续读档)→游戏(地图+省名+三态聊天+勾选下令+多存档+回菜单)；i18n外挂文件;DEBUG开关藏/显内脏。
- **编年史**：AI每年总结明面(结盟/敌对/军队)，仅公开。
- **测试**：53 pytest(单元/集成/系统) + playwright UI 全绿。

## 配置(conf/*.json, DIPLOMIND_CONFIG)
base_url/api_key/model/api/rounds/lang/concurrency/timeout/human;DIPLOMIND_DEBUG=1 开内脏。

## 未做(二期 backlog)
多人房间/邀请;AI调味到"三局看不穿"实测;整局到胜负节奏;好玩杠杆UI(背叛弹原话/关系连线图/称号);移动端;CI;尾延迟。

## 关键经验
4b全程开format;9b才挂;别用/v1;schema顺模型(dict);性格随机;记忆只读;人/AI同接口。详见 RESULTS/DECISIONS。
