# Tailscale スマホ外出先アクセス設定 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DipTriage が動作している Windows PC に、屋外のスマホから Tailscale VPN 経由でアクセスできるようにする

**Architecture:** Tailscale を PC とスマホの両方にインストールし、同一アカウントで認証することでプライベート仮想ネットワークを構築する。DipTriage はすでに `0.0.0.0:8000` でリッスンしており、コード変更は不要。PC の Tailscale IP は再起動後も固定される。

**Tech Stack:** Tailscale (WireGuard ベース VPN), DipTriage (FastAPI + Uvicorn on Windows)

**参照スペック:** `docs/superpowers/specs/2026-05-21-tailscale-remote-access-design.md`

---

## Task 1: Windows PC に Tailscale をインストール・ログイン

**Files:**
- 変更なし（外部ソフトウェアのインストール）

- [ ] **Step 1: インストーラーをダウンロード**

ブラウザで以下の URL を開き、Windows 用インストーラーをダウンロードする:
```
https://tailscale.com/download/windows
```
ファイル名例: `tailscale-setup-1.x.x-amd64.msi`

- [ ] **Step 2: インストーラーを実行**

ダウンロードした `.msi` ファイルをダブルクリック → 画面の指示に従ってインストール。
完了後、タスクトレイに Tailscale アイコン（緑の t）が現れる。

- [ ] **Step 3: Tailscale にログイン**

タスクトレイの Tailscale アイコンを左クリック → 「Log in...」を選択 → ブラウザが開く。
Google または GitHub アカウントでサインイン（新規アカウントは無料で作成可能）。

- [ ] **Step 4: ログイン確認**

PowerShell（管理者不要）を開き、以下を実行:
```powershell
tailscale status
```
期待される出力（例）:
```
100.78.34.12   your-pc-name     yuichi@gmail.com  windows -
```
`100.x.x.x` という IP アドレスが表示されれば OK。

---

## Task 2: Tailscale を Windows サービスとして自動起動設定

**Files:**
- 変更なし

- [ ] **Step 1: 「Run unattended」を有効化**

タスクトレイの Tailscale アイコンを**右クリック** → 「Preferences...」を開く。
「Run unattended」または「Start on login」チェックボックスをオンにする。

> これにより、PC 再起動後・ユーザーログイン前でも Tailscale が起動する。

- [ ] **Step 2: サービス稼働確認**

PowerShell を開き:
```powershell
Get-Service -Name Tailscale
```
期待される出力:
```
Status   Name      DisplayName
------   ----      -----------
Running  Tailscale Tailscale
```
`Running` であれば OK。

- [ ] **Step 3: PC の Tailscale IP を記録**

```powershell
tailscale ip -4
```
出力例: `100.78.34.12`

**この IP をメモしておく**（スマホからのアクセス URL になる）。

---

## Task 3: スマホに Tailscale をインストール・接続

**Files:**
- 変更なし（スマホアプリのインストール）

- [ ] **Step 1: スマホに Tailscale をインストール**

| OS | ストア |
|----|-------|
| iPhone | App Store で「Tailscale」を検索 |
| Android | Google Play で「Tailscale」を検索 |

- [ ] **Step 2: 同じアカウントでログイン**

アプリを起動 → 「Sign in」 → PC でログインしたものと**同じ** Google または GitHub アカウントを選択。

- [ ] **Step 3: VPN 接続を有効化**

アプリのメイン画面で「Connect」または接続トグルをオン。
初回は VPN 構成の追加許可を求められる → 「許可」。

---

## Task 4: スマホから DipTriage への接続確認

**Files:**
- 変更なし

- [ ] **Step 1: DipTriage が PC で動作していることを確認**

PC で `start_diptriage.bat` を起動、または既に起動中であることを確認。

- [ ] **Step 2: スマホブラウザからアクセス**

スマホのブラウザで以下の URL を開く（IP は Task 2 Step 3 で記録したもの）:
```
http://100.78.34.12:8000
```
DipTriage のダッシュボードが表示されれば成功。

- [ ] **Step 3: ブックマーク登録**

スマホブラウザで上記 URL をブックマーク登録しておく。
URL は PC の Tailscale IP が変わらない限り恒久的に使える。

---

## Task 5: (任意) MagicDNS で名前アクセスを有効化

IP アドレスの代わりに `http://your-pc-name:8000` という名前でアクセスしたい場合。

- [ ] **Step 1: Tailscale 管理コンソールを開く**

ブラウザで `login.tailscale.com/admin/dns` を開く。

- [ ] **Step 2: MagicDNS を有効化**

「Enable MagicDNS」ボタンをクリック。

- [ ] **Step 3: ホスト名確認**

```powershell
tailscale status
```
出力の `Hostname` 欄を確認（例: `diptriage-pc`）。

- [ ] **Step 4: スマホからホスト名でアクセス**

```
http://diptriage-pc:8000
```
または Tailscale が提供するドメイン形式:
```
http://diptriage-pc.tail12345.ts.net:8000
```

---

## 動作確認チェックリスト

| 確認項目 | 方法 |
|---------|------|
| PC で Tailscale が動作している | `tailscale status` → IP が表示される |
| スマホで Tailscale が接続中 | アプリのトグルが緑 |
| DipTriage が起動中 | PC ブラウザで `http://localhost:8000` が開く |
| スマホからアクセス可能 | スマホで `http://[Tailscale IP]:8000` が開く |

---

## トラブルシューティング

**スマホからアクセスできない場合:**

1. PC の Windows ファイアウォールがポート 8000 をブロックしている可能性がある:
   ```powershell
   # PowerShell（管理者）で実行
   New-NetFirewallRule -DisplayName "DipTriage" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```

2. Tailscale が両方の端末で「接続中」になっているか確認する

3. `tailscale ping [PC の Tailscale IP]` でスマホアプリから疎通確認できる機種もある
