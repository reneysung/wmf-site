#!/usr/bin/env python3
"""
字型字集檢查／重切。

為什麼需要這支：站上的 woff2 是 subset（只塞頁面真的用到的字），檔案小很多，
但**改文案多打一個 subset 裡沒有的字，那個字就會掉回系統字**，畫面上不報錯，
只是那一個字長得不一樣，很難用眼睛發現。這支把它變成跑一行就知道。

  python3 tools/fonts.py check            比對所有 HTML 需要的字 vs assets/*.subset.woff2
  python3 tools/fonts.py chars            印出三種字型各自需要的字集
  python3 tools/fonts.py build <原檔目錄>  用可變原檔重新切出 assets/*.subset.woff2

⚠️ 字型規則是**從每頁的 <style> 現場解析出來的**，不是寫死的。站上除了
   body / h1,h2,h3,.serif / .mono 之外還有 .faq-q、.prose-art h2、.prose-case h2、
   .case-thumb .placeholder 這些，之後誰再加一條 font-family 這支會自己跟上。

原檔（可變字重版，不進 repo，要用時再抓）：
  NotoSansTC-var.ttf     github.com/google/fonts/ofl/notosanstc/NotoSansTC[wght].ttf
  NotoSerifTC-var.ttf    github.com/google/fonts/ofl/notoseriftc/NotoSerifTC[wght].ttf
  JetBrainsMono-var.ttf  github.com/google/fonts/ofl/jetbrainsmono/JetBrainsMono[wght].ttf
build 需要 fonttools：pip install 'fonttools[woff]' brotli
"""
import sys, re, pathlib, subprocess
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = {
    'sans':  ('NotoSansTC.subset.woff2',    'NotoSansTC-var.ttf'),
    'serif': ('NotoSerifTC.subset.woff2',   'NotoSerifTC-var.ttf'),
    'mono':  ('JetBrainsMono.subset.woff2', 'JetBrainsMono-var.ttf'),
}
FAMILY = {'noto sans tc': 'sans', 'noto serif tc': 'serif', 'jetbrains mono': 'mono'}
# build 時把「原檔本身就沒有的字」記在這裡，check 就不會一直報那些永遠補不了的。
# 典型兩種：JetBrains Mono 是純拉丁字型（.mono 裡的中文一直都是掉到系統等寬字），
# 以及 ✔✕✖ 這類 Noto 沒收的符號。這些字會由系統字型顯示，是預期行為。
FALLBACK_FILE = ROOT / 'tools' / 'fonts-fallback.txt'
VOID = {'br','img','hr','meta','link','input','source','area','base','col','embed','param','track','wbr'}
SKIP = {'script','style','template','noscript','title'}

# 安全邊際：不管頁面現在有沒有用都塞進去，改文案最常多打的就是這些。
MARGIN = (
    ''.join(chr(c) for c in range(0x20, 0x7F))
    + '　，。、；：？！「」『』（）〈〉《》【】…—–‧·～｜／＼％＋－＝＜＞＃＆＊＠'
    + '０１２３４５６７８９'
    + '①②③④⑤⑥⑦⑧⑨⑩✓✔✕✖→←↑↓⋯★☆“”‘’'
)

# ---------- CSS ----------
def css_rules(html):
    """從 <style> 撈出 (選擇器, 桶子, 來源順序)，以及偽元素 content 產生的字。"""
    rules, gen = [], []          # gen: (字串, 桶子)
    order = 0
    for st in re.findall(r'<style[^>]*>(.*?)</style>', html, re.S):
        st = re.sub(r'/\*.*?\*/', ' ', st, flags=re.S)        # 去註解，不然會黏進選擇器
        for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', st):
            sel_raw, body = m.group(1).strip(), m.group(2)
            if sel_raw.startswith('@'):                        # @font-face / @media 的外層
                continue
            fm = re.search(r'font-family\s*:\s*([^;]+)', body)
            if not fm:
                continue
            fam = fm.group(1).strip().strip('"\'').split(',')[0].strip().strip('"\'').lower()
            bucket = FAMILY.get(fam)
            if not bucket:
                continue
            for sel in sel_raw.split(','):
                sel = ' '.join(sel.split())
                if not sel:
                    continue
                order += 1
                if '::' in sel or re.search(r'(?<!:):(before|after)\b', sel):
                    c = re.search(r'content\s*:\s*([^;]+)', body)
                    if c:
                        gen.append((unescape_css(c.group(1).strip()), bucket))
                    continue
                rules.append((parse_sel(sel), order, bucket))
    return rules, gen

def unescape_css(v):
    v = v.strip().strip('"\'')
    return re.sub(r'\\([0-9a-fA-F]{1,6})\s?', lambda m: chr(int(m.group(1), 16)), v)

def inline_bucket(style):
    """行內 style="...font-family:..." 也算數，站上 blog 有幾處是這樣寫的。"""
    m = re.search(r'font-family\s*:\s*([^;]+)', style or '')
    if not m:
        return None
    fam = m.group(1).strip().split(',')[0].strip().strip('"\'').lower()
    return FAMILY.get(fam)

def parse_sel(sel):
    """'.prose-art h2' → [({'tag':'div'...})...]；只支援 tag / .class / tag.class 與後代組合。"""
    parts = []
    for comp in sel.replace('>', ' ').split():
        tag = None
        classes = set()
        for bit in re.findall(r'[.#]?[A-Za-z0-9_-]+', comp):
            if bit.startswith('.'):
                classes.add(bit[1:])
            elif bit.startswith('#'):
                classes.add('#' + bit[1:])
            else:
                tag = bit.lower()
        parts.append((tag, classes))
    return parts

def spec(parts):
    return sum(len(c) for _, c in parts) * 100 + sum(1 for t, _ in parts if t)

def matches(parts, chain, i):
    """chain = [(tag, classes, id)] 由外到內；i = 要比對的元素位置。"""
    def hit(part, el):
        tag, cls = part
        if tag and tag != el[0]:
            return False
        return all((c[1:] == el[2]) if c.startswith('#') else (c in el[1]) for c in cls)
    if not hit(parts[-1], chain[i]):
        return False
    j, k = i - 1, len(parts) - 2
    while k >= 0:
        while j >= 0 and not hit(parts[k], chain[j]):
            j -= 1
        if j < 0:
            return False
        j -= 1; k -= 1
    return True

# ---------- HTML ----------
class Collector(HTMLParser):
    def __init__(self, rules):
        super().__init__(convert_charrefs=True)
        self.rules = rules
        self.chain = []                       # [(tag, classes, id, 行內style的桶)]
        self.out = {'sans': set(), 'serif': set(), 'mono': set()}

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = dict(attrs)
        self.chain.append((tag, set((a.get('class') or '').split()), a.get('id') or '',
                           inline_bucket(a.get('style') or '')))

    def handle_startendtag(self, tag, attrs):
        pass                                   # <x/> 不進堆疊

    def handle_endtag(self, tag):
        for i in range(len(self.chain) - 1, -1, -1):
            if self.chain[i][0] == tag:
                del self.chain[i:]
                return

    def bucket(self):
        # font-family 會繼承 → 由內往外，第一個有規則命中的祖先決定
        for i in range(len(self.chain) - 1, -1, -1):
            # 行內 style 的 font-family 贏過任何選擇器
            if self.chain[i][3]:
                return self.chain[i][3]
            best = None
            for parts, order, b in self.rules:
                if matches(parts, self.chain, i):
                    key = (spec(parts), order)
                    if best is None or key > best[0]:
                        best = (key, b)
            if best:
                return best[1]
        return 'sans'

    def handle_data(self, data):
        if not data.strip() or any(t in SKIP for t, _, _, _ in self.chain):
            return
        b = self.out[self.bucket()]
        for ch in data:
            if ch.strip():
                b.add(ch)

def pages():
    return sorted(p for p in ROOT.rglob('*.html') if '.git' not in p.parts)

def needed():
    out = {k: set(MARGIN) for k in ('sans', 'serif', 'mono')}
    ps = pages()
    for p in ps:
        html = p.read_text(encoding='utf-8', errors='replace')
        rules, gen = css_rules(html)
        c = Collector(rules)
        c.feed(html)
        for k in out:
            out[k] |= c.out[k]
        for text, b in gen:
            out[b] |= {ch for ch in text if ch.strip()}
    return out, ps

def load_fallback():
    out = {k: set() for k in FONTS}
    if FALLBACK_FILE.exists():
        for line in FALLBACK_FILE.read_text(encoding='utf-8').splitlines():
            if '\t' in line and not line.startswith('#'):
                k, chars = line.split('\t', 1)
                if k in out:
                    out[k] = set(chars)
    return out

def have(woff2):
    from fontTools.ttLib import TTFont
    return {chr(c) for c in TTFont(str(ROOT / 'assets' / woff2)).getBestCmap()}

# ---------- 指令 ----------
def cmd_chars():
    want, ps = needed()
    print(f'掃了 {len(ps)} 個 HTML')
    for k in ('sans', 'serif', 'mono'):
        print(f'\n[{k}] {len(want[k])} 字\n{"".join(sorted(want[k]))}')

def cmd_check():
    want, ps = needed()
    fb = load_fallback()
    print(f'掃了 {len(ps)} 個 HTML\n')
    bad = 0
    for k, (woff2, _) in FONTS.items():
        got = have(woff2)
        miss = sorted(want[k] - got - fb[k])
        skipped = len(want[k] & fb[k])
        note = f'（{skipped} 個原檔就沒有，由系統字型顯示）' if skipped else ''
        print(f'{"✅" if not miss else "❌"} {woff2:<26} 需要 {len(want[k]):>5} / 字型有 {len(got):>5} / 缺 {len(miss)} {note}')
        if miss:
            bad += 1
            print(f'     缺的字：{"".join(miss)}')
    if bad:
        print('\n有字掉在 subset 外面，那些字在頁面上會變成系統字。')
        print('重切：python3 tools/fonts.py build <放可變原檔的目錄>')
        sys.exit(1)
    print('\n三個字型都覆蓋得到，沒有掉字。')

def cmd_build(srcdir):
    from fontTools.ttLib import TTFont
    src = pathlib.Path(srcdir).expanduser().resolve()
    want, ps = needed()
    print(f'掃了 {len(ps)} 個 HTML')
    fallback = {}
    for k, (woff2, origin) in FONTS.items():
        o = src / origin
        if not o.exists():
            sys.exit(f'找不到原檔：{o}')
        source_has = {chr(c) for c in TTFont(str(o)).getBestCmap()}
        usable = want[k] & source_has
        fallback[k] = want[k] - source_has
        dst = ROOT / 'assets' / woff2
        before = dst.stat().st_size if dst.exists() else 0
        subprocess.run([
            sys.executable, '-m', 'fontTools.subset', str(o),
            '--text=' + ''.join(sorted(usable)),
            '--flavor=woff2', '--output-file=' + str(dst),
            '--layout-features=*', '--no-hinting', '--desubroutinize',
            '--drop-tables+=DSIG',
        ], check=True)
        miss = len(fallback[k])
        print(f'  {woff2:<26} {len(usable):>5} 字  {before:>7} → {dst.stat().st_size:>7} bytes'
              + (f'  （另有 {miss} 個原檔沒有，走系統字型）' if miss else ''))
    FALLBACK_FILE.write_text(
        '# build 自動產生：原檔本身沒有這些字，頁面上會由系統字型顯示。\n'
        '# 不要手改，重切字型時會重寫。\n'
        + ''.join(f'{k}\t{"".join(sorted(v))}\n' for k, v in fallback.items()),
        encoding='utf-8')
    print(f'\n切完了，原檔沒有的字記在 {FALLBACK_FILE.name}。跑 python3 tools/fonts.py check 驗一次。')

if __name__ == '__main__':
    a = sys.argv[1:] or ['check']
    if a[0] == 'check': cmd_check()
    elif a[0] == 'chars': cmd_chars()
    elif a[0] == 'build':
        if len(a) < 2: sys.exit('用法：python3 tools/fonts.py build <放可變原檔的目錄>')
        cmd_build(a[1])
    else: sys.exit(__doc__)
