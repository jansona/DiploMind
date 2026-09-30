/** Lightweight bilingual shell. Engine order strings and players' messages stay untouched. */
export let locale = (() => {
  try {
    return localStorage.getItem("diplomind.locale") || "zh";
  } catch {
    return "zh";
  }
})();
const words = {
  "Message acknowledged. Your newer draft is still unsent.":
    "上一条消息已确认，新草稿仍未发送。",
  "Unsent draft saved on this device.": "未发送的草稿已保存在此设备。",
  "Write a message before sending.": "请先输入消息内容。",
  "Sending… Your draft stays saved until the server acknowledges it.":
    "正在发送…服务器确认前，草稿会一直保留。",
  "Message acknowledged and staged for round-end delivery.":
    "服务器已确认，消息将在本轮结束时统一送达。",
  "Delivery unconfirmed. Your draft is saved; retry when ready.":
    "尚未确认送达，草稿已保留，可再次尝试发送。",
  "RETREAT ORDERS": "撤退命令",
  "WINTER ADJUSTMENTS": "冬季调整",
  "Live to fight again.": "保存实力，再战来日。",
  "A changing balance.": "势力在变，布局亦变。",
  "Choose adjustment": "选择调整命令",
  "Choose a retreat for each dislodged unit. Units without retreat orders are disbanded.":
    "为每个被击退的单位选择撤退地点，未收到撤退命令的单位将被解散。",
  "No units need orders this phase. Submit to confirm readiness.":
    "本阶段没有需要下令的单位，提交即可确认就绪。",
  "Choose from engine-legal orders": "从规则引擎允许的命令中选择",
  "Edit your draft order": "编辑命令草稿",
  "Retreat or disband": "撤退或解散",
  "The board is changing.": "战局正在变化。",
  "History has been made": "历史已经写就",

  "Orders sealed. You’re ready for resolution.": "命令已封存，等待结算。",
  "Orders accepted. The table is moving forward.": "命令已接收，棋局正在推进。",
  "Orders withdrawn. Your draft is ready to edit.":
    "命令已撤回，可以继续编辑草稿。",
  "Message staged. It will be delivered when the round closes.":
    "发言已暂存，将在本轮结束时统一送达。",
  "Your third message was accepted. You’re automatically ready for that round.":
    "第三条消息已确认，该轮已自动就绪，无需再点「我已就绪」。",
  "Ready confirmed for the previous round. Review the new round before your next action.":
    "上一轮已确认就绪。请先查看新一轮情况，再进行下一步操作。",
  "The round changed during your click. Review this round before choosing Ready.":
    "点击过程中已进入下一轮，请查看本轮情况后再选择「我已就绪」。",
  "Your third message automatically readies you. Choose Ready earlier to finish with fewer messages.":
    "发出第三条消息会自动就绪；少于三条也可点击「我已就绪」提前结束发言。",
  "You’re ready. Waiting for the remaining powers.":
    "你已就绪，等待其他国家完成。",
  "The command desk is open. Write your orders.": "指挥台已开放，请下达命令。",
  "The game begins. The first round of diplomacy is open.":
    "游戏开始，首轮外交谈判已经开放。",
  "Checkpoint saved for this room.": "已为此房间保存检查点。",
  "Checkpoint restored. The table is paused for review.":
    "检查点已恢复，棋局已暂停以便查看。",
  "The table is gathering": "棋局正在集结",
  "Your table is coming together.": "等待玩家入席。",
  "Claim a power. Invite your allies. Shape what comes next.":
    "选择国家，邀请盟友，共同改变未来。",
  "All orders resolve together. Choose your next move.":
    "所有命令同时结算，想好你的下一步。",
  "This browser is using the fully playable 2D board.":
    "此浏览器使用可完整游玩的二维棋盘。",
  "The map could not refresh. Your command desk is still available.":
    "地图暂时无法刷新，仍可使用指挥台。",
  "The first chapter is yet to be written. Complete a movement phase to begin the chronicle.":
    "第一章尚待书写，完成一个移动阶段后即可开始记录战史。",
  "The table could not initialize. Refresh the page to try again.":
    "棋局初始化失败，请刷新页面重试。",
  "Cannot reach the table. Check your connection and try again.":
    "无法连接棋局，请检查网络后重试。",
  "Your session is no longer valid. Rejoin the table with your saved seat or choose an open power.":
    "当前会话已失效，请使用已保存的席位重连，或选择空缺国家。",

  "THE DIPLOMATIC TABLE": "外交战略棋局",
  "A game of words. A world of consequences.": "言语之间，世界随之改变。",
  "How to play": "玩法指南",
  "EUROPE, 1901 · YOUR NEXT MOVE": "欧洲，1901 · 你的下一步",
  "History is written": "历史，写在",
  "between the lines.": "言外之意。",
  "Seven powers. One continent. Allies with agendas.":
    "七大强国，一片大陆，各怀心思的盟友。",
  "Take your seat at the table and make every promise count.":
    "加入棋局，让每一句承诺都成为战略。",
  "Take your seat": "加入棋局",
  "Join a table": "加入房间",
  "Classic Diplomacy. Human ambition.": "经典《外交》，真实的野心。",
  "A new kind of opponent.": "新的对手，同样值得认真对待。",
  "THE EUROPEAN THEATRE": "欧洲战局",
  "EUROPEAN THEATRE": "欧洲战局",
  "7 POWERS · 34 CENTERS": "7 大强国 · 34 个补给中心",
  "A living strategy table": "立体战略棋盘",
  "18 supply centers to victory": "控制 18 个补给中心即可独胜",
  "MAKE YOUR NEXT ALLIANCE": "下一段联盟，从这里开始",
  "Open tables": "开放棋局",
  "↻ Refresh": "↻ 刷新",
  "A fresh page in history.": "历史的新一页。",
  "No open tables yet. Yours could be the first.":
    "目前还没有开放房间，创建第一局吧。",
  "Create a table →": "创建棋局 →",
  "Your seat is waiting": "你的席位仍然保留",
  "Return to this browser’s current table.": "返回此浏览器中尚未结束的棋局。",
  "Return to table →": "返回棋局 →",
  "DIPLOMIND / AN OPEN-SOURCE STRATEGY EXPERIENCE":
    "DIPLOMIND / 开源外交策略游戏",
  "Trust is a strategy. So is doubt.": "信任是战略，怀疑亦然。",
  Table: "棋盘",
  History: "战史",
  Room: "房间",
  Tables: "大厅",
  Invite: "邀请",
  CLASSIC: "经典模式",
  Live: "已连接",
  Reconnecting: "正在重连",
  Negotiation: "谈判",
  "Write orders": "下达命令",
  Resolution: "结算",
  "No time limit": "不限时",
  "Waiting for host": "等待房主",
  "Ⅱ Paused": "Ⅱ 已暂停",
  "Select a piece to plan your move": "选择棋子，规划下一步",
  "Supply center": "补给中心",
  Army: "陆军",
  Fleet: "海军",
  "Drag to pan · Scroll to zoom · Right-drag to orbit":
    "拖动平移 · 滚轮缩放 · 右键旋转",
  "Click a unit · Choose a legal order": "选择单位 · 下达合法命令",
  "THE BALANCE OF POWER": "势力对比",
  "SUPPLY CENTERS": "补给中心",
  "/ 18 TO WIN": "/ 18 个独胜",
  YOU: "你",
  HUMAN: "玩家",
  AI: "AI",
  HOST: "房主",
  GUEST: "观战",
  "YOUR POWER": "你的国家",
  Observer: "观战者",
  "A VIEW FROM THE GALLERY": "观战席",
  "The public table, unfolding": "观察公开的战局与谈判",
  "Command desk": "指挥台",
  Diplomacy: "外交谈判",
  "YOUR ORDERS": "你的命令",
  "Every move matters.": "每一步，都有分量。",
  "Choose a unit on the map or below to write an order.":
    "在地图或下方选择单位，草拟命令。",
  "Choose a unit on the map or below. Draft one legal order for each unit.":
    "在地图或下方选择单位，每个单位可草拟一道合法命令。",
  "Your pieces are in position. The host will open the first round of diplomacy.":
    "部队已经就位，等待房主开始首轮外交谈判。",
  "Diplomacy comes first. Your units will be ready when the command desk opens.":
    "先进行外交谈判，谈判结束后即可下达命令。",
  "Orders open after diplomacy": "谈判结束后开放命令",
  "Use the Diplomacy tab to propose your next alliance.":
    "打开「外交谈判」，向潜在盟友提出方案。",
  "Drafts stay on your device until you submit.":
    "提交前，草稿只保存在你的设备上。",
  "Clear draft orders": "清空命令草稿",
  "Withdraw orders": "撤回已提交命令",
  "Awaiting your command": "等待你的命令",
  "No order drafted": "尚未草拟命令",
  DRAFT: "草稿",
  SEALED: "已提交",
  "Order type": "命令类型",
  Destination: "目标省份",
  "Legal order": "合法命令",
  "Unit and action to support": "支援的单位与行动",
  "Army and convoy destination": "运输的陆军与目的地",
  "Hold position": "原地驻守",
  Move: "移动",
  Support: "支援",
  Convoy: "海运",
  Retreat: "撤退",
  Build: "建造",
  Disband: "解散",
  "Waive build": "放弃建造",
  "Add to orders ✓": "加入草稿 ✓",
  "Update draft ✓": "更新草稿 ✓",
  Remove: "移除",
  "AT THE TABLE": "棋局中的玩家",
  "HUMANS AT THE TABLE": "真人玩家席位",
  "ORDER STATUS": "命令状态",
  NEGOTIATION: "谈判状态",
  "Considering…": "思考中…",
  "✓ Ready": "✓ 已就绪",
  "At the table": "参与棋局",
  "AI fills this seat": "由 AI 接管",
  "Orders are sealed.": "命令已经封存。",
  "Your orders are ready. Withdraw them to edit before resolution begins.":
    "命令已提交，在结算开始前仍可撤回修改。",
  "You can withdraw only before the table begins resolving.":
    "仅能在棋局开始结算前撤回命令。",
  "✓ Ready for resolution": "✓ 等待结算",
  "Orders submitted ✓": "命令已提交 ✓",
  "Resolving orders…": "正在结算…",
  "THE OPENING POSITION": "初始部署",
  "OBSERVER DESK": "观战指挥台",
  "A world in motion.": "见证世界的变化。",
  "Great strategies reveal themselves over time.":
    "真正的战略，往往在时间中显现。",
  "THE CONVERSATION": "外交交涉",
  "Words before war.": "兵戎之前，先交言辞。",
  "◎ Public": "◎ 公开频道",
  "PUBLIC CHANNEL · Visible to all powers and observers":
    "公开频道 · 所有国家和观战者可见",
  "Every alliance begins": "每一段联盟，",
  "with a few words.": "都始于几句话。",
  "Some words are best": "有些话，适合",
  "shared in confidence.": "在私下交流。",
  "The conversation opens when the game begins.": "游戏开始后开放谈判。",
  "Be the first to make a proposal.": "率先提出你的外交方案。",
  "Stage message →": "暂存发言 →",
  "Ready · finish this round": "我已就绪 · 结束本轮",
  "✓ Ready · waiting for the table": "✓ 已就绪 · 等待其他国家",
  "Messages are delivered together when everyone is ready.":
    "所有国家就绪后，本轮发言将同时送达。",
  "Your messages are queued. Waiting for the other powers to finish.":
    "发言已暂存，等待其他国家完成本轮。",
  "QUEUED FOR ROUND-END DELIVERY": "已暂存，待本轮结束统一送达",
  "Negotiation opens next movement phase": "下个移动阶段开放外交谈判",
  "DIPLOMATIC DISPATCH": "外交消息",
  "Observers can read public messages. Private channels remain hidden.":
    "观战者只能阅读公开发言，私聊内容不会公开。",
  "A PLACE AT THE TABLE": "为你留一席",
  "Your world. Your next move.": "你的世界，你的下一步。",
  "Create a table": "创建房间",
  Classic: "经典模式",
  "THE ORIGINAL GAME": "原版规则",
  "The authentic rules. Seven powers, simultaneous orders, and 18 supply centers for a solo victory.":
    "忠于原版规则：七大强国，同时下令，控制 18 个补给中心即可独胜。",
  "Table name": "房间名称",
  "Your name": "你的昵称",
  "Your power": "选择国家",
  "AI dialogue": "AI 对话语言",
  "Room passcode": "房间口令",
  optional: "可选",
  "Invite friends before starting. AI will fill all unclaimed powers.":
    "开局前邀请朋友加入，空缺国家将由 AI 补足。",
  "Create table": "创建房间",
  "Room code": "房间码",
  "Choose your power": "选择国家",
  "if required": "如有设置",
  "Claim an open power or observe the public table. A saved seat in this browser reconnects automatically.":
    "选择空缺国家或观战，此浏览器保存的席位可自动续接。",
  "Join table": "加入房间",
  "Observe the table": "观战",
  "BEHIND CLOSED DOORS": "私下交涉",
  "A quieter conversation.": "开启一段私密对话。",
  "Only the selected powers can read this channel. Choose who gets a seat.":
    "仅选中的国家可以阅读此频道，请选择交流对象。",
  "Open private channel →": "创建私聊频道 →",
  "YOUR TABLE": "你的棋局",
  "Room details": "房间信息",
  Rules: "规则",
  "Classic Diplomacy": "经典《外交》",
  "Your seat": "你的席位",
  Players: "参与者",
  Status: "状态",
  Lobby: "准备中",
  Playing: "进行中",
  Paused: "已暂停",
  Ended: "已结束",
  "Start the game →": "开始游戏 →",
  "Start game →": "开始游戏 →",
  "Pause game": "暂停游戏",
  "Resume game →": "继续游戏 →",
  "Resume →": "继续 →",
  "Negotiation clock": "谈判计时",
  "90 seconds": "90 秒",
  "3 minutes": "3 分钟",
  "5 minutes": "5 分钟",
  "Save checkpoint": "保存检查点",
  "Load checkpoint": "载入检查点",
  "End this game": "结束本局",
  "Make host": "转让房主",
  "Human player": "真人玩家",
  "Year limit": "自定义年份上限",
  "Your table is ready. Invite friends or start with AI filling the open powers.":
    "房间已准备好，可以邀请朋友，或让 AI 补足空缺国家后开局。",
  "Waiting for the host to start. Your seat has been reserved.":
    "等待房主开局，你的席位已保留。",
  "The table is paused. Drafts are saved; play resumes when the host is ready.":
    "棋局已暂停，草稿仍然保留，等待房主继续。",
  "View chronicle →": "查看战史 →",
  "The host has ended this game.": "房主已结束本局。",
  "THE RECORD OF A CHANGING WORLD": "记录变化中的世界",
  "Chronicle of the table.": "这一局的编年史。",
  "The first chapter is yet to be written.": "故事的第一章，尚待书写。",
  "YOUR FIRST CAMPAIGN": "第一次踏入外交战场",
  "Diplomacy, in a few moves.": "几步了解《外交》。",
  "Make your case": "提出你的方案",
  "Write your orders": "草拟你的命令",
  "Commit together": "同时提交，同时结算",
  "Control the centers": "控制补给中心",
  "Talk publicly or in a private channel. Stage up to three messages per round. The third message automatically readies you; press Ready earlier to finish with fewer messages. Everyone’s messages arrive together. Promises are never binding.":
    "可以公开发言，也可以创建私聊。每轮最多暂存三条消息，发出第三条会自动就绪；少于三条也可点击「我已就绪」提前结束发言。发言统一送达，而承诺从不等于保证。",
  "Select one of your pieces. Choose a legal hold, move, support, or convoy. Every unit gets at most one order. You can edit drafts freely before submission.":
    "选择你的单位，安排驻守、移动、支援或海运。每个单位只能收到一道命令，提交前可自由编辑草稿。",
  "Orders resolve simultaneously. Equal strength bounces. Support adds strength, but an attack can cut it. A fleet can convoy an army across a sea.":
    "所有命令同时结算，实力相当的进攻会互相阻挡。支援能增加力量，但可能被攻击切断。海军可以运输陆军跨海。",
  "Capture supply centers in autumn to sustain more units. Retreat dislodged units and build at your vacant home centers. Reach 18 centers for a solo victory.":
    "秋季占领补给中心后，可维持更多部队。被击退的单位需要撤退，空闲的本土中心可以造兵。达到 18 个中心即可独胜。",
  "Reading the board": "认识棋盘",
  "▲ Army · ▰ Fleet · ◉ Supply center": "▲ 陆军 · ▰ 海军 · ◉ 补给中心",
  "The command desk offers only engine-legal orders. A legal order can still fail when another power’s orders conflict.":
    "指挥台只展示规则引擎允许的命令，但合法命令仍可能因与其他国家的行动冲突而失败。",
  "Understood. To the table →": "明白了，返回棋局 →",
  "Offline demo AI": "离线演示 AI",
  "Deterministic heuristic opponents. No language-model inference.":
    "使用确定性启发式对手，未调用语言模型。",
  "AI provider": "AI 服务",
  "Provider readiness": "接入状态",
  "Available does not mean authenticated or live-tested.":
    "可用不代表已经登录或通过真实调用验证。",
  "Configured provider · connection unverified": "已配置服务 · 连接尚未验证",
  "Provider status unavailable": "暂时无法获取 AI 服务状态",
  ready: "就绪",
  configuration_required: "需要配置",
  disabled: "未启用",
  unverified: "尚未验证",
  not_installed: "尚未安装",
  Austria: "奥地利",
  England: "英格兰",
  France: "法国",
  Germany: "德国",
  Italy: "意大利",
  Russia: "俄国",
  Turkey: "土耳其",
  English: "English",
  "The European Accord": "欧洲协定",
  Commander: "指挥官",
};
const originals = new WeakMap();
export function translate(text) {
  if (locale === "en") return text;
  const key = text.trim().replace(/\s+/g, " ");
  let value = words[key];
  if (!value) {
    value = key
      .replace(/Supply center/g, "补给中心")
      .replace(/A new diplomatic chapter/g, "开启新的外交篇章")
      .replace(/Retreats required/g, "需要下达撤退命令")
      .replace(/Winter adjustments/g, "冬季调整")
      .replace(
        /^You may build (\d+) units? at vacant home centers\. Unused builds are waived\.$/,
        "你可以在空闲的本土中心建造 $1 个单位，未使用的建造机会将被放弃。",
      )
      .replace(
        /^Choose (\d+) units? to disband\. Only legal adjustments are shown\.$/,
        "请选择 $1 个单位解散，下方仅显示合法的调整命令。",
      )
      .replace(
        /\b(Spring|Autumn|Winter) (\d{4})\b/g,
        (_, s, y) =>
          `${y} 年${{ Spring: "春季", Autumn: "秋季", Winter: "冬季" }[s]}`,
      )
      .replace(/^(\d+) messages? left this round$/, "本轮还可发送 $1 条消息")
      .replace(/^(\d+) orders? drafted$/, "已草拟 $1 道命令")
      .replace(/^(\d+) will hold$/, "$1 个单位将驻守")
      .replace(/^(\d+) will disband$/, "$1 个单位将解散")
      .replace(/^(\d+) builds unused$/, "$1 次建造将放弃")
      .replace(/^(\d+) disbands left$/, "还需解散 $1 个单位")
      .replace(/^Submit (\d+) orders?$/, "提交 $1 道命令")
      .replace(/^Submit holds$/, "提交驻守命令")
      .replace(/^Submit adjustments$/, "提交调整命令")
      .replace(/^Submit disbands$/, "提交解散命令")
      .replace(/^PRIVATE · Visible only to /, "私聊 · 仅以下国家可见：")
      .replace(/ · you$/, " · 你")
      .replace(/ supply centers$/, " 个补给中心")
      .replace(/^(\d+) humans · (\d+) AI$/, "$1 位真人 · $2 个 AI")
      .replace(/^(\d+) AI powers?$/, "$1 个 AI 国家")
      .replace(/^(\d+:\d+) remaining$/, "剩余 $1")
      .replace(
        /^Negotiation round (\d+) · Make your words count$/,
        "外交谈判第 $1 轮 · 言语亦有分量",
      )
      .replace(/^Move → /, "移动 → ")
      .replace(/^Retreat → /, "撤退 → ")
      .replace(/^Support /, "支援 ")
      .replace(/^Convoy /, "海运 ")
      .replace(/^Build army/, "建造陆军")
      .replace(/^Build fleet/, "建造海军")
      .replace(/^Disband army/, "解散陆军")
      .replace(/^Disband fleet/, "解散海军")
      .replace(/ · occupied$/, " · 已占用")
      .replace(/ · game in progress$/, " · 游戏已开始");
    for (const country of [
      "Austria",
      "England",
      "France",
      "Germany",
      "Italy",
      "Russia",
      "Turkey",
    ])
      value = value.replace(
        new RegExp("\\b" + country + "\\b", "g"),
        words[country],
      );
  }
  return value === key ? text : text.replace(text.trim(), value);
}
function processText(node) {
  if (
    node.parentElement?.closest(
      "script,style,canvas,[data-no-translate],.chat-body,.staged-message,#history-content,#header-context,#room-label,.room-card h3,#room-modal-title",
    )
  )
    return;
  const prior = originals.get(node);
  const source =
    prior && node.nodeValue === prior.rendered ? prior.source : node.nodeValue;
  const rendered = translate(source);
  if (node.nodeValue !== rendered) node.nodeValue = rendered;
  originals.set(node, { source, rendered });
}
export function localize() {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) processText(walker.currentNode);
  document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  const button = document.getElementById("locale-button");
  if (button && button.textContent !== (locale === "zh" ? "EN" : "中文"))
    button.textContent = locale === "zh" ? "EN" : "中文";
  const placeholders = {
    "The European Accord": "欧洲协定",
    "Leave blank for an open table": "留空则无需口令",
    "A proposal, a promise, a little persuasion…":
      "一个提议，一句承诺，一点说服力…",
  };
  for (const el of document.querySelectorAll("[placeholder]")) {
    if (!el.dataset.placeholderOriginal)
      el.dataset.placeholderOriginal = el.placeholder;
    el.placeholder =
      locale === "zh"
        ? placeholders[el.dataset.placeholderOriginal] ||
          el.dataset.placeholderOriginal
        : el.dataset.placeholderOriginal;
  }
}
export function initLocale(onChange) {
  const observer = new MutationObserver(() => localize());
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  const button = document.getElementById("locale-button");
  button.onclick = () => {
    locale = locale === "zh" ? "en" : "zh";
    try {
      localStorage.setItem("diplomind.locale", locale);
    } catch {}
    onChange?.();
    localize();
  };
  localize();
}
