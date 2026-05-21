# Tailscale によるスマホ外出先アクセス設計

**日付**: 2026-05-21  
**対象**: DipTriage（FastAPI, Windows PC 常時起動）

---

## コンテキスト

DipTriage は Windows PC でローカル実行されており、現在は TeamViewer 経由でしかリモートアクセスできない。
屋外でスマホから直接 Web UI にアクセスできるようにするため、Tailscale VPN を導入する。

Cloudflare アカウントはあるがドメインを持っていないため、永続 URL を得るには Tailscale が最も手順が少なく確実。

---

## アーキテクチャ

```
[スマホ（Tailscaleアプリ）]
        |
  Tailscale VPN（WireGuard ベース）
        |
[Windows PC（Tailscale サービス）]
        |
  DipTriage: 0.0.0.0:8000
```

Tailscale は両端末をプライベート仮想ネットワークに参加させる。
PC の Tailscale IP（`100.x.x.x`）またはホスト名（`[pc-name].tailnet.ts.net`）はアカウント内で固定される。

---

## 変更範囲

**コード変更なし。**

- `start_diptriage.bat` はすでに `--host 0.0.0.0` で起動しており、Tailscale インターフェースからのアクセスも受け付ける。
- アプリ側に追加作業は不要。

---

## セットアップ手順

### PC 側（Windows）

1. [tailscale.com/download](https://tailscale.com/download) から Windows インストーラーをダウンロード・実行
2. Tailscale アプリを起動 → ログイン（Google または GitHub アカウントで可）
3. ログイン後、タスクトレイの Tailscale アイコンを右クリック → **「Run unattended」（サービスとして自動起動）** を有効化
4. Tailscale 管理画面（`login.tailscale.com/admin/machines`）で PC のマシン名と IP を確認

### スマホ側

5. App Store / Google Play から「Tailscale」をインストール
6. 同じアカウントでログイン
7. Tailscale を「接続中」状態にする

### アクセス確認

8. スマホのブラウザで `http://[PC の Tailscale IP]:8000` を開く  
   例: `http://100.78.34.12:8000`
9. ブックマーク登録で次回から即アクセス可能

---

## URL の永続性

| 状況 | URL |
|------|-----|
| PC 再起動後 | 変わらない |
| スマホが別の Wi-Fi / 4G に移動 | 変わらない |
| Tailscale 再接続後 | 変わらない |

---

## セキュリティ特性

- URL が漏れても、Tailscale に登録していない端末からはアクセス不可
- PC 側ファイアウォール・ルーターのポート開放は不要
- 通信は WireGuard で暗号化

---

## コスト

- 個人利用: **無料**（最大 100 台、帯域制限なし）
- Tailscale アカウント（Google/GitHub でサインイン可能）が必要

---

## 将来の拡張（今回のスコープ外）

- MagicDNS を有効にすれば IP の代わりに `diptriage-pc` のような名前でアクセス可能
- Cloudflare Access を後日追加すれば、Tailscale を使わない端末向けの認証付き公開も可能
