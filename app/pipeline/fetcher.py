"""第0段階：yfinance からの株価データ取得"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import NamedTuple

import io
import requests
import pandas as pd
import yfinance as yf

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DipTriage/1.0; +https://github.com/DipTriage)"}

logger = logging.getLogger(__name__)

_NIKKEI225_FALLBACK: list[tuple[str, str]] = [
    # Fisheries
    ("1301", "Kyokuyo"), ("1332", "Nippon Suisan Kaisha"), ("1333", "Maruha Nichiro"),
    # Mining
    ("1605", "Inpex"),
    # Construction
    ("1721", "Comsys Holdings"), ("1801", "Taisei"), ("1802", "Obayashi"),
    ("1803", "Shimizu"), ("1808", "Haseko"), ("1812", "Kajima"),
    ("1925", "Daiwa House Industry"), ("1928", "Sekisui House"), ("1963", "JGC Holdings"),
    # Food
    ("2002", "Nisshin Seifun Group"), ("2269", "Meiji Holdings"), ("2282", "NH Foods"),
    ("2501", "Sapporo Holdings"), ("2502", "Asahi Group Holdings"), ("2503", "Kirin Holdings"),
    ("2531", "Takara Holdings"), ("2801", "Kikkoman"), ("2802", "Ajinomoto"),
    ("2871", "Nichirei"), ("2914", "Japan Tobacco"),
    # Services / Advertising
    ("2413", "M3"), ("2432", "DeNA"), ("2433", "Hakuhodo DY Holdings"),
    ("4324", "Dentsu Group"), ("6098", "Recruit Holdings"),
    # Wholesale
    ("2768", "Sojitz"), ("8001", "Itochu"), ("8002", "Marubeni"),
    ("8015", "Toyota Tsusho"), ("8031", "Mitsui & Co"), ("8053", "Sumitomo"),
    ("8058", "Mitsubishi"),
    # Retail
    ("3086", "J. Front Retailing"), ("3099", "Isetan Mitsukoshi Holdings"),
    ("3382", "Seven & i Holdings"), ("8233", "Takashimaya"), ("8252", "Marui Group"),
    ("8267", "Aeon"), ("9983", "Fast Retailing"),
    # Textiles
    ("3101", "Toyobo"), ("3103", "Unitika"), ("3105", "Nisshinbo Holdings"),
    ("3401", "Teijin"), ("3402", "Toray Industries"), ("3407", "Asahi Kasei"),
    # Real Estate
    ("3289", "Tokyu Fudosan Holdings"), ("8801", "Mitsui Fudosan"),
    ("8802", "Mitsubishi Estate"), ("8804", "Tokyo Tatemono"),
    ("8830", "Sumitomo Realty & Development"),
    # Pulp & Paper
    ("3861", "Oji Holdings"), ("3863", "Nippon Paper Industries"),
    # Silicon Wafers
    ("3436", "SUMCO"),
    # Chemicals
    ("4004", "Resonac Holdings"), ("4005", "Sumitomo Chemical"), ("4021", "Nissan Chemical"),
    ("4042", "Tosoh"), ("4043", "Tokuyama"), ("4061", "Denka"),
    ("4063", "Shin-Etsu Chemical"), ("4183", "Mitsui Chemicals"),
    ("4188", "Mitsubishi Chemical Group"), ("4208", "UBE"), ("4272", "Nippon Kayaku"),
    ("4452", "Kao"), ("4631", "DIC"),
    # Pharmaceuticals
    ("4151", "Kyowa Kirin"), ("4502", "Takeda Pharmaceutical"), ("4503", "Astellas Pharma"),
    ("4506", "Sumitomo Pharma"), ("4507", "Shionogi"), ("4519", "Chugai Pharmaceutical"),
    ("4523", "Eisai"), ("4527", "Rohto Pharmaceutical"), ("4543", "Terumo"),
    ("4568", "Daiichi Sankyo"), ("4578", "Otsuka Holdings"),
    # Cosmetics
    ("4911", "Shiseido"),
    # Photography & Imaging
    ("4901", "Fujifilm Holdings"), ("4902", "Konica Minolta"),
    # Petroleum
    ("5019", "Idemitsu Kosan"), ("5020", "ENEOS Holdings"),
    # Rubber
    ("5101", "Yokohama Rubber"), ("5108", "Bridgestone"),
    # Glass & Ceramics
    ("5201", "AGC"), ("5214", "Nippon Electric Glass"), ("5233", "Taiheiyo Cement"),
    ("5301", "Tokai Carbon"), ("5332", "Toto"), ("5333", "NGK Insulators"),
    # Steel
    ("5401", "Nippon Steel"), ("5406", "Kobe Steel"), ("5411", "JFE Holdings"),
    ("5631", "Japan Steel Works"),
    # Non-Ferrous Metals
    ("5703", "Nippon Light Metal Holdings"), ("5706", "Mitsui Mining and Smelting"),
    ("5707", "Toho Zinc"), ("5711", "Mitsubishi Materials"), ("5713", "Sumitomo Metal Mining"),
    ("5714", "DOWA Holdings"), ("5715", "Furukawa"), ("5801", "Furukawa Electric"),
    ("5802", "Sumitomo Electric Industries"), ("5803", "Fujikura"),
    # Machinery
    ("6103", "Okuma"), ("6113", "Amada"), ("6141", "DMG Mori"), ("6301", "Komatsu"),
    ("6302", "Sumitomo Heavy Industries"), ("6305", "Hitachi Construction Machinery"),
    ("6326", "Kubota"), ("6361", "Ebara"), ("6367", "Daikin Industries"),
    ("6370", "Kurita Water Industries"), ("6376", "Nichias"), ("6383", "Daifuku"),
    ("6471", "NSK"), ("6472", "NTN"), ("6473", "JTEKT"), ("6479", "Minebea Mitsumi"),
    # Electrical Machinery & Electronics
    ("6178", "Japan Post Holdings"), ("6501", "Hitachi"), ("6503", "Mitsubishi Electric"),
    ("6504", "Fuji Electric"), ("6506", "Yaskawa Electric"), ("6508", "Meidensha"),
    ("6594", "Nidec"), ("6645", "Omron"), ("6674", "GS Yuasa"),
    ("6701", "NEC"), ("6702", "Fujitsu"), ("6703", "Oki Electric Industry"),
    ("6724", "Seiko Epson"), ("6752", "Panasonic Holdings"), ("6753", "Sharp"),
    ("6758", "Sony Group"), ("6762", "TDK"), ("6770", "Alps Alpine"),
    ("6857", "Advantest"), ("6902", "Denso"), ("6952", "Casio Computer"),
    ("6954", "Fanuc"), ("6971", "Kyocera"), ("6976", "Taiyo Yuden"),
    ("6981", "Murata Manufacturing"), ("6988", "Nitto Denko"),
    # Shipbuilding & Heavy Industry
    ("7011", "Mitsubishi Heavy Industries"), ("7012", "Kawasaki Heavy Industries"),
    ("7013", "IHI"),
    # Automotive
    ("7201", "Nissan Motor"), ("7202", "Isuzu Motors"), ("7203", "Toyota Motor"),
    ("7205", "Hino Motors"), ("7211", "Mitsubishi Motors"), ("7261", "Mazda Motor"),
    ("7267", "Honda Motor"), ("7269", "Suzuki Motor"), ("7270", "Subaru"),
    ("7272", "Yamaha Motor"),
    # Precision Instruments
    ("7731", "Nikon"), ("7733", "Olympus"), ("7735", "Screen Holdings"),
    ("7751", "Canon"), ("7752", "Ricoh"), ("7762", "Citizen Watch"),
    # Other Products
    ("7832", "Bandai Namco Holdings"), ("7911", "Toppan Holdings"),
    ("7912", "Dai Nippon Printing"), ("7951", "Yamaha"), ("7974", "Nintendo"),
    # Banks
    ("7182", "Japan Post Bank"), ("8304", "Aozora Bank"),
    ("8306", "Mitsubishi UFJ Financial Group"), ("8308", "Resona Holdings"),
    ("8309", "Sumitomo Mitsui Trust Holdings"), ("8316", "Sumitomo Mitsui Financial Group"),
    ("8354", "Fukuoka Financial Group"), ("8411", "Mizuho Financial Group"),
    # Securities & Finance
    ("8591", "Orix"), ("8601", "Daiwa Securities Group"), ("8604", "Nomura Holdings"),
    ("8628", "Matsui Securities"), ("8697", "Japan Exchange Group"),
    # Insurance
    ("8630", "Sompo Holdings"), ("8725", "MS&AD Insurance Group"),
    ("8750", "Dai-ichi Life Holdings"), ("8766", "Tokio Marine Holdings"),
    ("8795", "T&D Holdings"),
    # Railway & Land Transport
    ("9001", "Tobu Railway"), ("9005", "Tokyu"), ("9007", "Odakyu Electric Railway"),
    ("9008", "Keio"), ("9009", "Keisei Electric Railway"), ("9020", "East Japan Railway"),
    ("9021", "West Japan Railway"), ("9022", "Central Japan Railway"),
    ("9064", "Yamato Holdings"), ("9147", "Nippon Express Holdings"),
    # Shipping
    ("9101", "Nippon Yusen"), ("9104", "Mitsui OSK Lines"), ("9107", "Kawasaki Kisen Kaisha"),
    # Airlines
    ("9202", "ANA Holdings"),
    # Telecom & IT
    ("9432", "NTT"), ("9433", "KDDI"), ("9434", "SoftBank"),
    # Electric Power & Gas
    ("9501", "Tokyo Electric Power"), ("9502", "Chubu Electric Power"),
    ("9503", "Kansai Electric Power"), ("9531", "Tokyo Gas"), ("9532", "Osaka Gas"),
    # Other Services
    ("9602", "Toho"), ("9735", "Secom"), ("9766", "Konami Holdings"),
    ("9984", "SoftBank Group"),
]

US_SECTOR_ETF_MAP: dict[str, str] = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}


class PriceRow(NamedTuple):
    symbol: str
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    adj_close: float | None


class IndexPriceRow(NamedTuple):
    symbol: str
    date: str
    close: float
    change_pct: float | None


_NIKKEI225_NAMES_JA: dict[str, str] = {
    "1301": "極洋", "1332": "日本水産", "1333": "マルハニチロ",
    "1605": "INPEX",
    "1721": "コムシスホールディングス", "1801": "大成建設", "1802": "大林組",
    "1803": "清水建設", "1808": "長谷工コーポレーション", "1812": "鹿島建設",
    "1925": "大和ハウス工業", "1928": "積水ハウス", "1963": "日揮ホールディングス",
    "2002": "日清製粉グループ本社", "2269": "明治ホールディングス", "2282": "日本ハム",
    "2501": "サッポロホールディングス", "2502": "アサヒグループホールディングス",
    "2503": "キリンホールディングス", "2531": "宝ホールディングス",
    "2801": "キッコーマン", "2802": "味の素", "2871": "ニチレイ", "2914": "日本たばこ産業",
    "2413": "エムスリー", "2432": "ディー・エヌ・エー", "2433": "博報堂DYホールディングス",
    "4324": "電通グループ", "6098": "リクルートホールディングス",
    "2768": "双日", "8001": "伊藤忠商事", "8002": "丸紅", "8015": "豊田通商",
    "8031": "三井物産", "8053": "住友商事", "8058": "三菱商事",
    "3086": "Jフロントリテイリング", "3099": "三越伊勢丹ホールディングス",
    "3382": "セブン&アイ・ホールディングス", "8233": "高島屋", "8252": "丸井グループ",
    "8267": "イオン", "9983": "ファーストリテイリング",
    "3101": "東洋紡", "3103": "ユニチカ", "3105": "日清紡ホールディングス",
    "3401": "帝人", "3402": "東レ", "3407": "旭化成",
    "3289": "東急不動産ホールディングス", "8801": "三井不動産", "8802": "三菱地所",
    "8804": "東京建物", "8830": "住友不動産",
    "3861": "王子ホールディングス", "3863": "日本製紙",
    "3436": "SUMCO",
    "4004": "レゾナック・ホールディングス", "4005": "住友化学", "4021": "日産化学",
    "4042": "東ソー", "4043": "トクヤマ", "4061": "デンカ", "4063": "信越化学工業",
    "4183": "三井化学", "4188": "三菱ケミカルグループ", "4208": "UBE",
    "4272": "日本化薬", "4452": "花王", "4631": "DIC",
    "4151": "協和キリン", "4502": "武田薬品工業", "4503": "アステラス製薬",
    "4506": "住友ファーマ", "4507": "塩野義製薬", "4519": "中外製薬",
    "4523": "エーザイ", "4527": "ロート製薬", "4543": "テルモ",
    "4568": "第一三共", "4578": "大塚ホールディングス",
    "4911": "資生堂",
    "4901": "富士フイルムホールディングス", "4902": "コニカミノルタ",
    "5019": "出光興産", "5020": "ENEOSホールディングス",
    "5101": "横浜ゴム", "5108": "ブリヂストン",
    "5201": "AGC", "5214": "日本電気硝子", "5233": "太平洋セメント",
    "5301": "東海カーボン", "5332": "TOTO", "5333": "日本碍子",
    "5401": "日本製鉄", "5406": "神戸製鋼所", "5411": "JFEホールディングス",
    "5631": "日本製鋼所",
    "5703": "日本軽金属ホールディングス", "5706": "三井金属鉱業", "5707": "東邦亜鉛",
    "5711": "三菱マテリアル", "5713": "住友金属鉱山", "5714": "DOWAホールディングス",
    "5715": "古河機械金属", "5801": "古河電気工業", "5802": "住友電気工業",
    "5803": "フジクラ",
    "6103": "オークマ", "6113": "アマダ", "6141": "DMG森精機", "6301": "コマツ",
    "6302": "住友重機械工業", "6305": "日立建機", "6326": "クボタ",
    "6361": "荏原製作所", "6367": "ダイキン工業", "6370": "栗田工業",
    "6376": "ニチアス", "6383": "ダイフク", "6471": "日本精工", "6472": "NTN",
    "6473": "JTEKT", "6479": "ミネベアミツミ",
    "6178": "日本郵政", "6501": "日立製作所", "6503": "三菱電機",
    "6504": "富士電機", "6506": "安川電機", "6508": "明電舎", "6594": "ニデック",
    "6645": "オムロン", "6674": "GSユアサ", "6701": "NEC", "6702": "富士通",
    "6703": "沖電気工業", "6724": "セイコーエプソン",
    "6752": "パナソニック ホールディングス", "6753": "シャープ",
    "6758": "ソニーグループ", "6762": "TDK", "6770": "アルプスアルパイン",
    "6857": "アドバンテスト", "6902": "デンソー", "6952": "カシオ計算機",
    "6954": "ファナック", "6971": "京セラ", "6976": "太陽誘電",
    "6981": "村田製作所", "6988": "日東電工",
    "7011": "三菱重工業", "7012": "川崎重工業", "7013": "IHI",
    "7201": "日産自動車", "7202": "いすゞ自動車", "7203": "トヨタ自動車",
    "7205": "日野自動車", "7211": "三菱自動車工業", "7261": "マツダ",
    "7267": "本田技研工業", "7269": "スズキ", "7270": "SUBARU", "7272": "ヤマハ発動機",
    "7731": "ニコン", "7733": "オリンパス", "7735": "SCREENホールディングス",
    "7751": "キヤノン", "7752": "リコー", "7762": "シチズン時計",
    "7832": "バンダイナムコホールディングス", "7911": "凸版印刷",
    "7912": "大日本印刷", "7951": "ヤマハ", "7974": "任天堂",
    "7182": "ゆうちょ銀行", "8304": "あおぞら銀行",
    "8306": "三菱UFJフィナンシャル・グループ", "8308": "りそなホールディングス",
    "8309": "三井住友トラスト・ホールディングス",
    "8316": "三井住友フィナンシャルグループ",
    "8354": "ふくおかフィナンシャルグループ", "8411": "みずほフィナンシャルグループ",
    "8591": "オリックス", "8601": "大和証券グループ本社", "8604": "野村ホールディングス",
    "8628": "松井証券", "8697": "日本取引所グループ",
    "8630": "SOMPOホールディングス",
    "8725": "MS&ADインシュアランスグループホールディングス",
    "8750": "第一生命ホールディングス", "8766": "東京海上ホールディングス",
    "8795": "T&Dホールディングス",
    "9001": "東武鉄道", "9005": "東急", "9007": "小田急電鉄", "9008": "京王電鉄",
    "9009": "京成電鉄", "9020": "東日本旅客鉄道", "9021": "西日本旅客鉄道",
    "9022": "東海旅客鉄道", "9064": "ヤマトホールディングス",
    "9147": "日本通運",
    "9101": "日本郵船", "9104": "商船三井", "9107": "川崎汽船",
    "9202": "ANAホールディングス",
    "9432": "日本電信電話", "9433": "KDDI", "9434": "ソフトバンク",
    "9501": "東京電力ホールディングス", "9502": "中部電力", "9503": "関西電力",
    "9531": "東京ガス", "9532": "大阪ガス",
    "9602": "東宝", "9735": "セコム", "9766": "コナミグループ", "9984": "ソフトバンクグループ",
}


class StockInfo(NamedTuple):
    symbol: str
    name: str
    market: str
    exchange: str | None
    sector: str | None
    sector_etf: str | None
    index_name: str
    name_ja: str | None = None


def get_sp500_symbols() -> list[StockInfo]:
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=_HEADERS, timeout=15,
        ).text
        tables = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})
        df = tables[0]
        result = []
        for _, row in df.iterrows():
            symbol = str(row["Symbol"]).replace(".", "-")
            sector = str(row.get("GICS Sector", ""))
            result.append(StockInfo(
                symbol=symbol,
                name=str(row.get("Security", symbol)),
                market="US",
                exchange=str(row.get("Exchange", None)),
                sector=sector if sector else None,
                sector_etf=US_SECTOR_ETF_MAP.get(sector),
                index_name="S&P500",
            ))
        logger.info("S&P 500: %d symbols fetched", len(result))
        return result
    except Exception as e:
        logger.error("Failed to fetch S&P 500 symbols: %s", e)
        return []


def get_nikkei225_symbols() -> list[StockInfo]:
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/Nikkei_225",
            headers=_HEADERS, timeout=15,
        ).text
        tables = pd.read_html(io.StringIO(html))
        # Nikkei 225 の表は複数あるので、Code 列を持つものを探す
        for df in tables:
            code_col = None
            for c in df.columns:
                if "code" in str(c).lower():
                    code_col = c
                    break
            if code_col is None:
                continue

            name_col = None
            for c in df.columns:
                if "name" in str(c).lower() or "company" in str(c).lower():
                    name_col = c
                    break

            result = []
            for _, row in df.iterrows():
                code = str(row[code_col]).strip().zfill(4)
                if not code.isdigit():
                    continue
                symbol = f"{code}.T"
                name = str(row[name_col]) if name_col else symbol
                result.append(StockInfo(
                    symbol=symbol,
                    name=name,
                    market="JP",
                    exchange="TSE",
                    sector=None,
                    sector_etf=None,
                    index_name="Nikkei225",
                    name_ja=_NIKKEI225_NAMES_JA.get(code),
                ))
            if result:
                logger.info("Nikkei 225: %d symbols fetched", len(result))
                return result
    except Exception as e:
        logger.error("Failed to fetch Nikkei 225 symbols: %s", e)
    logger.warning("Nikkei 225 web scraping failed; using hardcoded fallback (%d symbols)", len(_NIKKEI225_FALLBACK))
    return [
        StockInfo(
            symbol=f"{code}.T",
            name=name,
            market="JP",
            exchange="TSE",
            sector=None,
            sector_etf=None,
            index_name="Nikkei225",
            name_ja=_NIKKEI225_NAMES_JA.get(code),
        )
        for code, name in _NIKKEI225_FALLBACK
    ]


_JPX_LISTED_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)


def get_tse_segment_symbols(segment: str, index_name: str) -> list[StockInfo]:
    """JPX の上場銘柄一覧 Excel から指定市場区分の銘柄を取得する。

    segment: "スタンダード（内国株式）" or "グロース（内国株式）"
    """
    try:
        resp = requests.get(_JPX_LISTED_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content), header=0, dtype=str, engine="xlrd")
        market_col = next((c for c in df.columns if "市場" in str(c)), None)
        code_col   = next((c for c in df.columns if "コード" in str(c)), None)
        name_col   = next((c for c in df.columns if "銘柄名" in str(c)), None)
        if market_col is None or code_col is None or name_col is None:
            logger.error("JPX Excel: expected columns not found. columns=%s", list(df.columns))
            return []
        filtered = df[df[market_col] == segment]
        result = []
        for _, row in filtered.iterrows():
            code = str(row[code_col]).strip().split(".")[0].zfill(4)
            if not code.isdigit():
                continue
            result.append(StockInfo(
                symbol=f"{code}.T",
                name=str(row[name_col]),
                market="JP",
                exchange="TSE",
                sector=None,
                sector_etf=None,
                index_name=index_name,
            ))
        logger.info("%s: %d symbols fetched from JPX", index_name, len(result))
        return result
    except Exception as e:
        logger.error("Failed to fetch %s symbols from JPX: %s", index_name, e)
        return []


def fetch_prices(symbols: list[str], days: int = 2, end_date: str | None = None) -> dict[str, pd.DataFrame]:
    """複数銘柄の株価を一括取得。{symbol: DataFrame} を返す。
    end_date: "YYYY-MM-DD" 形式。省略時は今日。バックフィル時に指定する。
    """
    if not symbols:
        return {}

    period_days = max(days + 5, 10)  # 休場日を考慮して余分に取得
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end = datetime.now()
    start = end - timedelta(days=period_days)

    try:
        raw = yf.download(
            symbols,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as e:
        logger.error("yf.download failed: %s", e)
        return {}

    result: dict[str, pd.DataFrame] = {}

    if len(symbols) == 1:
        sym = symbols[0]
        if not raw.empty:
            if isinstance(raw.columns, pd.MultiIndex):
                # yfinance 0.2.38+ may return MultiIndex even for single ticker
                try:
                    df = raw[sym].dropna(how="all")
                    if not df.empty:
                        result[sym] = df
                except KeyError:
                    pass
            else:
                result[sym] = raw
    else:
        for sym in symbols:
            try:
                df = raw[sym].dropna(how="all")
                if not df.empty:
                    result[sym] = df
            except KeyError:
                pass

    return result


def extract_price_rows(sym: str, df: pd.DataFrame, n_days: int = 2) -> list[PriceRow]:
    """DataFrame から直近 n_days 日分の PriceRow を抽出する。"""
    rows = []
    for dt, row in df.tail(n_days).iterrows():
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        close = float(row["Close"]) if "Close" in row and not pd.isna(row["Close"]) else None
        if close is None:
            continue
        vol = float(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else None
        if vol == 0.0:
            vol = None
        rows.append(PriceRow(
            symbol=sym,
            date=date_str,
            open=float(row["Open"]) if "Open" in row and not pd.isna(row["Open"]) else None,
            high=float(row["High"]) if "High" in row and not pd.isna(row["High"]) else None,
            low=float(row["Low"]) if "Low" in row and not pd.isna(row["Low"]) else None,
            close=close,
            volume=vol,
            adj_close=None,  # auto_adjust=True のため Close = Adj Close
        ))
    return rows


def fetch_index_price_rows(index_symbols: list[str], end_date: str | None = None) -> list[IndexPriceRow]:
    """指数（^GSPC, ^N225 等）の直近2日分を取得し変化率を計算する。"""
    prices = fetch_prices(index_symbols, days=5, end_date=end_date)
    rows = []
    for sym, df in prices.items():
        df = df.sort_index()
        closes = df["Close"].dropna().tail(2)
        if len(closes) < 2:
            continue
        prev_close, today_close = float(closes.iloc[-2]), float(closes.iloc[-1])
        change_pct = (today_close - prev_close) / prev_close * 100
        date_str = pd.Timestamp(closes.index[-1]).strftime("%Y-%m-%d")
        rows.append(IndexPriceRow(
            symbol=sym,
            date=date_str,
            close=today_close,
            change_pct=change_pct,
        ))
    return rows
