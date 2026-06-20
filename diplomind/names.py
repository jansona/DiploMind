"""Standard map province abbreviations -> (English, 中文)."""
PROVINCES = {
    "BOH": ("Bohemia", "波希米亚"), "BUD": ("Budapest", "布达佩斯"), "GAL": ("Galicia", "加利西亚"),
    "TRI": ("Trieste", "的里雅斯特"), "TYR": ("Tyrolia", "蒂罗尔"), "VIE": ("Vienna", "维也纳"),
    "CLY": ("Clyde", "克莱德"), "EDI": ("Edinburgh", "爱丁堡"), "LVP": ("Liverpool", "利物浦"),
    "LON": ("London", "伦敦"), "WAL": ("Wales", "威尔士"), "YOR": ("York", "约克"),
    "BRE": ("Brest", "布雷斯特"), "BUR": ("Burgundy", "勃艮第"), "GAS": ("Gascony", "加斯科涅"),
    "MAR": ("Marseilles", "马赛"), "PAR": ("Paris", "巴黎"), "PIC": ("Picardy", "皮卡第"),
    "BER": ("Berlin", "柏林"), "KIE": ("Kiel", "基尔"), "MUN": ("Munich", "慕尼黑"),
    "PRU": ("Prussia", "普鲁士"), "RUH": ("Ruhr", "鲁尔"), "SIL": ("Silesia", "西里西亚"),
    "APU": ("Apulia", "阿普利亚"), "NAP": ("Naples", "那不勒斯"), "PIE": ("Piedmont", "皮埃蒙特"),
    "ROM": ("Rome", "罗马"), "TUS": ("Tuscany", "托斯卡纳"), "VEN": ("Venice", "威尼斯"),
    "LVN": ("Livonia", "利沃尼亚"), "MOS": ("Moscow", "莫斯科"), "SEV": ("Sevastopol", "塞瓦斯托波尔"),
    "STP": ("St Petersburg", "圣彼得堡"), "UKR": ("Ukraine", "乌克兰"), "WAR": ("Warsaw", "华沙"),
    "ANK": ("Ankara", "安卡拉"), "ARM": ("Armenia", "亚美尼亚"), "CON": ("Constantinople", "君士坦丁堡"),
    "SMY": ("Smyrna", "士麦那"), "SYR": ("Syria", "叙利亚"), "ALB": ("Albania", "阿尔巴尼亚"),
    "BEL": ("Belgium", "比利时"), "BUL": ("Bulgaria", "保加利亚"), "DEN": ("Denmark", "丹麦"),
    "FIN": ("Finland", "芬兰"), "GRE": ("Greece", "希腊"), "HOL": ("Holland", "荷兰"),
    "NWY": ("Norway", "挪威"), "POR": ("Portugal", "葡萄牙"), "RUM": ("Rumania", "罗马尼亚"),
    "SER": ("Serbia", "塞尔维亚"), "SPA": ("Spain", "西班牙"), "SWE": ("Sweden", "瑞典"),
    "TUN": ("Tunis", "突尼斯"), "NAF": ("North Africa", "北非"), "ADR": ("Adriatic Sea", "亚得里亚海"),
    "AEG": ("Aegean Sea", "爱琴海"), "BAL": ("Baltic Sea", "波罗的海"), "BAR": ("Barents Sea", "巴伦支海"),
    "BLA": ("Black Sea", "黑海"), "BOT": ("Gulf of Bothnia", "波的尼亚湾"), "EAS": ("East Med.", "东地中海"),
    "ENG": ("English Channel", "英吉利海峡"), "HEL": ("Helgoland", "黑尔戈兰湾"), "ION": ("Ionian Sea", "爱奥尼亚海"),
    "IRI": ("Irish Sea", "爱尔兰海"), "LYO": ("Gulf of Lyon", "里昂湾"), "MAO": ("Mid-Atlantic", "中大西洋"),
    "NAO": ("North Atlantic", "北大西洋"), "NTH": ("North Sea", "北海"), "NWG": ("Norwegian Sea", "挪威海"),
    "SKA": ("Skagerrak", "斯卡格拉克"), "TYS": ("Tyrrhenian Sea", "第勒尼安海"), "WES": ("West Med.", "西地中海"),
    "SWI": ("Switzerland", "瑞士"),
}


def label(abbr: str) -> str:
    en, zh = PROVINCES.get(abbr, (abbr, ""))
    return f"{abbr}={en}/{zh}" if zh else abbr
