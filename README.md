# Meteora DLMM Monitoring Bot (Read-Only)

Bot **monitoring saja** untuk posisi likuiditas Anda di [Meteora DLMM](https://app.meteora.ag) (Solana).
Bot ini membaca data posisi secara berkala dan mengirim **notifikasi Telegram**
ketika salah satu dari 4 kondisi terpenuhi. Semua keputusan eksekusi
(tutup posisi, dll) tetap dilakukan **manual** oleh Anda lewat app Meteora.

## Batasan Keamanan (WAJIB DIBACA)

- Bot ini **tidak pernah** meminta, menyimpan, atau menggunakan private key /
  seed phrase. Yang dibutuhkan hanya **wallet address publik** Anda — sama
  seperti melihat wallet siapa pun di Solscan.
- Tidak ada kode di project ini yang membangun, menandatangani, atau mengirim
  transaksi Solana apa pun. Satu-satunya fungsi SDK yang dipanggil adalah
  fungsi baca resmi `DLMM.getAllLbPairPositionsByUser()` dari
  [`@meteora-ag/dlmm`](https://github.com/MeteoraAg/dlmm-sdk) — lihat
  `node_reader/fetch_positions.js`.
- Kalau repo atau server yang menjalankan bot ini bocor, penyerang paling
  banter cuma bisa melihat posisi Anda (yang memang sudah publik di
  blockchain) dan token Telegram bot Anda — dana Anda tetap aman karena tidak
  ada kunci privat yang bisa dipakai untuk memindahkan apa pun.

## Empat Kondisi Notifikasi

1. **Stop Loss (⛔)** — PnL posisi <= `sl_percent` (default -10%).
2. **Trailing Stop (🔒 → 📉 / ⚠️)** —
   - PnL mencapai `tp_floor_lock` (default +3%) → notifikasi *floor lock aktif*, mulai lacak peak PnL.
   - Peak PnL turun `tp_trailing_drawdown` poin persen (default 5pp) → notifikasi *trailing stop terpicu*.
   - PnL turun kembali persis ke `tp_floor_lock` → notifikasi pengingat terakhir sebelum wilayah SL.
3. **Fast TP (🎯)** — PnL lompat langsung ke >= `tp_fast_threshold` (default +5%) tanpa sempat melewati tahap floor-lock bertahap.
4. **Idle Timeout (⏰)** — posisi belum pernah masuk range harga selama `idle_timeout_hours` (default 3 jam), dihitung dari **waktu posisi benar-benar dibuat on-chain** (bukan dari kapan bot pertama kali melihatnya, kalau data itu berhasil diambil - lihat catatan di bawah).

Setiap kondisi hanya dikirim **sekali per posisi** (disimpan di SQLite),
supaya tidak spam notifikasi berulang.

Selain 4 kondisi di atas, ada juga:

- **Peringatan bot bermasalah (⚠️/✅)** — kalau bot gagal membaca posisi
  beberapa kali berturut-turut (default 3x, atur lewat
  `monitoring.failure_alert_threshold`), Anda dapat 1 notifikasi peringatan
  supaya "tidak ada notif" tidak disalahartikan sebagai "semua aman". Begitu
  berhasil baca lagi, dapat notifikasi pemulihan.
- **Ringkasan harian (📊)** — tiap hari jam 08:00 WITA (Bali), dapat 1 pesan berisi
  status semua posisi aktif (PnL, peak, status range) sekaligus, tidak
  perlu menunggu sampai ada masalah untuk tahu kondisi posisi Anda.

## Arsitektur

```
Solana RPC ─┐
            ├─▶ node_reader/fetch_positions.js  (READ-ONLY, @meteora-ag/dlmm SDK)
            │        │  JSON via stdout
            │        ▼
            │   src/meteora_client.py  (subprocess wrapper)
            │        │
            │        ▼
Jupiter ────┴─▶ src/price_provider.py  (harga USD token + symbol)
                     │
                     ▼
              src/main.py  (loop polling)
                     │        │
                     ▼        ▼
          src/conditions.py   src/state_store.py (SQLite: peak PnL, flag notif, dst)
                     │
                     ▼
              src/notifier.py  (Telegram sendMessage)
```

Data posisi Meteora DLMM (bin range, jumlah token, fee) hanya bisa dibaca
dengan benar lewat SDK resminya, yang saat ini hanya tersedia dalam
TypeScript (`@meteora-ag/dlmm`) — belum ada SDK Python resmi. Karena itu
project ini pakai satu script Node.js kecil **khusus baca data** sebagai
sumber data, sementara seluruh logika bot (kondisi, state, Telegram)
tetap di Python sesuai permintaan. `node_reader/fetch_positions.js`
sengaja dibuat sesempit mungkin (satu file, satu fungsi SDK) supaya mudah
diaudit bahwa tidak ada fungsi sign/withdraw yang menyelinap masuk.

## Batasan Perhitungan PnL (penting untuk dipahami)

DLMM di Meteora tidak menyimpan "nilai deposit awal" per posisi secara
on-chain yang gampang dibaca. Bot ini memakai pendekatan praktis:

- **Baseline PnL = nilai USD posisi saat pertama kali bot melihatnya**,
  disimpan ke SQLite (`data/state.db`) dan dipakai terus sebagai acuan
  selama posisi tersebut belum "hilang" dari wallet (dianggap closed).
- Konsekuensinya: kalau Anda menjalankan bot **beberapa saat setelah**
  posisi dibuka (harga sudah bergerak), baseline yang tercatat bukan harga
  deposit asli, melainkan nilai saat bot mulai memantau.
- **Rekomendasi**: jalankan bot sesegera mungkin setelah membuka posisi
  baru supaya baseline PnL akurat.
- **Fee yang sudah diklaim ikut dihitung** sebagai bagian dari nilai posisi
  (`total_claimed_fee_x/y`, kumulatif, tidak pernah berkurang). Jadi kalau
  Anda klaim fee manual lewat app Meteora, PnL yang dihitung bot **tidak**
  tiba-tiba turun - klaim fee cuma memindahkan nilai dari "belum diklaim"
  ke "sudah diklaim", tetap dihitung sebagai milik Anda.
- **Waktu pembuatan posisi** untuk hitungan idle-timeout diambil dari
  transaksi on-chain paling awal di alamat posisi tersebut (butuh 1 kali
  panggilan RPC tambahan, cuma dilakukan sekali per posisi baru - bukan
  tiap poll). Kalau lookup ini gagal, bot pakai waktu pertama kali dia
  melihat posisi tersebut sebagai fallback (sama seperti PnL baseline).

## Struktur Project

```
meteora-lp-notif-bot/
├── config.example.yaml   # template config (copy ke config.yaml)
├── .env.example          # template secret Telegram (copy ke .env)
├── requirements.txt
├── node_reader/           # script Node.js read-only (SDK @meteora-ag/dlmm)
│   ├── package.json
│   └── fetch_positions.js
├── scripts/
│   ├── test_read_position.py       # sanity-check baca wallet, tanpa kirim notif
│   ├── send_sample_notifications.py # kirim contoh tiap jenis notif ke Telegram
│   └── send_daily_summary.py        # kirim 1x ringkasan harian semua posisi
├── src/
│   ├── config.py           # load config.yaml + .env
│   ├── models.py           # dataclass RawPosition / ValuedPosition
│   ├── meteora_client.py   # panggil node_reader via subprocess (READ-ONLY)
│   ├── price_provider.py   # harga token USD (Jupiter + fallback DexScreener) + resolve symbol
│   ├── conditions.py       # logika 4 kondisi notifikasi (pure function)
│   ├── state_store.py      # persist state ke SQLite (posisi + kesehatan bot)
│   ├── notifier.py         # kirim pesan Telegram
│   ├── logging_setup.py    # log file + journal JSONL (jurnal trading)
│   ├── timeutil.py         # format waktu WITA (Bali)
│   └── main.py             # loop polling utama (multi-wallet)
├── data/                   # data/state.db (SQLite, di-gitignore)
└── logs/                   # bot.log + evaluations.jsonl (di-gitignore)
```

## Setup

### 1. Buat Telegram bot & dapatkan chat ID

1. Chat ke [@BotFather](https://t.me/BotFather) di Telegram, kirim `/newbot`,
   ikuti instruksinya. Simpan **token** yang diberikan.
2. Chat ke bot seperti [@userinfobot](https://t.me/userinfobot) untuk
   mendapatkan **chat ID** Anda sendiri.
3. Kirim satu pesan apa saja ke bot Anda (buka chat-nya, klik Start) supaya
   bot punya izin mengirim pesan ke Anda.

### 2. Siapkan wallet address publik

Wallet address yang Anda pakai untuk LP di Meteora — bukan private key,
cukup alamat publiknya (yang biasa Anda paste ke Solscan/Explorer). Bot
ini bisa pantau **lebih dari satu wallet sekaligus** kalau perlu (isi
`wallet_addresses` sebagai daftar di `config.yaml`, lihat langkah 4).

### 3. Install dependencies

```bash
# Python
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Node.js (untuk pembaca posisi read-only)
cd node_reader
npm install
cd ..
```

Butuh Node.js versi 18+ terpasang di sistem.

### 4. Isi config

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

- Edit `config.yaml`: isi `wallet_addresses` (daftar, bisa 1 atau lebih)
  dan sesuaikan threshold kalau perlu.
- Edit `.env`: isi `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID`.

```yaml
wallet_addresses:
  - "WALLET_PUBLIK_PERTAMA_ANDA"
  - "WALLET_PUBLIK_KEDUA_ANDA"   # opsional, hapus kalau cuma 1 wallet
```

RPC default memakai RPC publik Solana mainnet-beta untuk testing. Kalau
nanti sering kena rate limit (terutama kalau polling makin cepat / posisi
banyak), ganti `solana.rpc_url` di `config.yaml` ke RPC berbayar seperti
Helius atau QuickNode.

### 5. Sanity check: baca satu wallet dulu

Sebelum menjalankan bot penuh, pastikan pembacaan posisi & harga sudah benar:

```bash
python -m scripts.test_read_position
```

Script ini mencetak semua posisi DLMM aktif di wallet Anda beserta estimasi
nilai USD-nya, tanpa menyimpan state dan tanpa mengirim notifikasi apa pun.

### 6. Jalankan bot

```bash
python -m src.main
```

Untuk testing satu kali poll saja (tanpa loop terus-menerus):

```bash
python -m src.main --once
```

Biarkan bot berjalan di background/VPS kecil atau laptop yang menyala.
Untuk menjalankan sebagai service di Linux, bisa dibuatkan systemd unit
atau dijalankan lewat `tmux`/`screen`/`pm2` (mengatur proses Python biasa).

## Alternatif Tanpa VPS/Laptop Menyala: GitHub Actions

Kalau Anda tidak mau/tidak bisa menyiapkan VPS atau membiarkan laptop
menyala terus, repo ini sudah dilengkapi workflow
`.github/workflows/monitor.yml` yang menjalankan satu siklus pemantauan
secara otomatis di server GitHub — tidak perlu install apa pun di
komputer Anda, cukup atur lewat halaman web GitHub.

**Trade-off yang perlu dipahami**: jadwal di GitHub Actions berjalan
tiap **5 menit** (batas minimum praktis yang direkomendasikan GitHub sendiri
— di bawah itu jadwalnya jadi tidak reliable, bisa diubah), bukan tiap
30-60 detik seperti kalau bot dijalankan terus-menerus di VPS/laptop atau
hosting selalu-nyala (Railway/Render, lihat `Dockerfile` di repo ini kalau
nanti butuh). Untuk kebanyakan pemantauan LP ini cukup memadai, tapi kalau
harga bergerak sangat cepat dalam hitungan menit, notifikasi SL/TP bisa
telat sampai ~5 menit (kadang lebih saat server GitHub sedang sibuk,
jadwal cron tidak dijamin presisi).

Cara mengaktifkan:

1. Buka halaman repo Anda di GitHub, lalu ke **Settings → Secrets and
   variables → Actions → New repository secret**.
2. Tambahkan 3 secret berikut (nama harus persis sama, huruf besar semua):
   - `WALLET_ADDRESSES` — wallet address publik Anda; kalau lebih dari satu,
     pisahkan dengan koma, contoh: `wallet1xxx,wallet2xxx`
     (secret lama bernama `WALLET_ADDRESS`/tunggal juga masih didukung)
   - `TELEGRAM_BOT_TOKEN` — token dari @BotFather
   - `TELEGRAM_CHAT_ID` — chat ID Anda dari @userinfobot
3. Selesai — workflow otomatis mulai jalan sesuai jadwal. Anda juga bisa
   memicu satu kali run manual kapan saja lewat tab **Actions** di repo →
   pilih workflow **Meteora DLMM Monitor** → tombol **Run workflow**.
4. Hasil tiap poll bisa dilihat di tab **Actions** (klik run yang mana
   saja → lihat log step "Run one monitoring poll"). State (peak PnL,
   status notifikasi) otomatis di-commit balik ke repo di file
   `data/state.db` supaya tidak hilang antar-run.
5. Tiap hari jam 08:00 WITA (Bali), workflow yang sama otomatis mengirim 1 pesan
   ringkasan status semua posisi (lihat step "Send daily summary").

Kalau mau ubah interval 5 menit atau jam ringkasan harian itu, edit baris
`cron:` di `.github/workflows/monitor.yml` (format cron standar, 5 field,
dalam UTC — ingat sesuaikan juga kondisi `if:` di step ringkasan harian
kalau jamnya diubah).

## Coba Kirim Contoh Notifikasi / Ringkasan

- `python -m scripts.send_sample_notifications` — kirim 1 contoh untuk
  tiap jenis notifikasi (SL, floor-lock, trailing stop, floor touch, fast
  TP, idle timeout) ke Telegram Anda, pakai data rekaan (bukan wallet
  asli), diberi label "CONTOH/TEST" supaya tidak membingungkan.
- `python -m scripts.send_daily_summary` — kirim ringkasan status semua
  posisi yang sedang dipantau (dari data yang sudah tersimpan), kapan saja
  tanpa menunggu jadwal jam 08:00 WITA.

## Membaca Log

- `logs/bot.log` — log operasional (error, info start/stop, hasil kirim notif).
- `logs/evaluations.jsonl` — satu baris JSON per posisi per poll (bukan cuma
  yang trigger notifikasi), berisi PnL, status in-range, peak PnL, dst.
  Bisa dipakai untuk audit / jurnal trading (bandingkan dengan keputusan
  manual Anda nanti).

## Catatan Endpoint Pihak Ketiga

- Harga token USD diambil dari Jupiter Price API (`price_api.base_url` di
  `config.yaml`) sebagai sumber utama, dengan **fallback otomatis ke
  DexScreener** untuk token yang tidak ada datanya di Jupiter (umum untuk
  token pump.fun yang sangat baru). Endpoint API pihak ketiga bisa berubah
  dari waktu ke waktu (Jupiter sendiri sudah beberapa kali migrasi versi
  endpoint harga). Kalau bot mulai gagal ambil harga, cek endpoint terbaru
  di [dev.jup.ag](https://dev.jup.ag) dan update `price_api.base_url` —
  tidak perlu ubah kode.
- Link posisi di notifikasi disusun dari `meteora.app_base_url` +
  alamat LB pair (`https://app.meteora.ag/dlmm/<lb_pair_address>`). Buka
  link ini dengan wallet Anda terhubung di app Meteora untuk melihat posisi.

## Setelah Fase Read-Only Ini Terbukti Andal

Bot ini murni "mata", bukan "tangan" — tidak ada fungsi apa pun di sini
untuk modify/close/withdraw posisi. Kalau setelah beberapa minggu Anda
merasa notifikasinya akurat dan nyaman dipakai, barulah pertimbangkan
upgrade ke versi eksekusi otomatis dengan wallet terpisah bermodal
terbatas — sebagai project terpisah, tidak menyentuh kode di repo ini.
