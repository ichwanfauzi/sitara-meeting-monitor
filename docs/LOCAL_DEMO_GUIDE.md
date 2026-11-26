# Panduan Demo Lokal SITARA

Panduan ini menyiapkan demo di komputer lokal. Gunakan hanya data sintetis; jangan memasukkan notulen, daftar peserta, kredensial, atau dokumen rapat yang nyata.

## Kondisi lokal saat panduan disiapkan

- Frontend tersedia di `http://127.0.0.1:5173/`.
- API lokal merespons `http://127.0.0.1:8000/api/v1/health`.
- Database yang dipakai saat panduan ini diverifikasi adalah `sitara_dev`, dengan migrasi `0026_notification_email_delivery`.
- Migrasi baru `0027_brief_optional_priority` harus diterapkan dengan `alembic upgrade head` sebelum menyimpan Decision Brief baru yang tidak mengisi prioritas.
- Sudah ada dua rapat sintetis:
  - `DEMO-RAPIM-2026-11-01` — Monitoring Program Prioritas Semester Genap.
  - `DEMO-RAPIM-2026-11-02` — Koordinasi Kemitraan dan Komunikasi Internal.
- Saat pengecekan, email notifikasi aktif dan worker email berjalan. Karena itu gunakan alur baca-saja selama demo.

Status di atas menggambarkan komputer lokal saat panduan ini disiapkan dan dapat berubah.

## Menjalankan aplikasi

Jika layanan belum berjalan, dari PowerShell di root repository:

```powershell
docker compose up -d
```

Jika frontend belum berjalan:

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1
```

Buka `http://127.0.0.1:5173/`. Pastikan API sehat dengan:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health" -UseBasicParsing
```

Jangan mengaktifkan profile `notification-email` untuk demo. Worker email sudah berjalan pada kondisi lokal yang diperiksa.

## Alur presentasi yang disarankan

1. Masuk memakai akun lokal sintetis yang sudah tersedia. Gunakan akun **Rektor** bila tersedia agar presentasi tetap baca-saja.
2. Tunjukkan Dashboard, lalu buka salah satu rapat `DEMO-RAPIM` untuk melihat agenda dan notulensi.
3. Tunjukkan Decision Brief dari rapat yang sama.
4. Buka Repository untuk memperlihatkan arsip rapat dan dokumen terkait.
5. Buka Tindak Lanjut untuk memperlihatkan daftar tugas, tenggat, dan status; buka detail tanpa mengubah data.

Email notifikasi saat ini aktif. Jangan membuat atau mengedit tugas, mengubah status, atau mengirim/meninjau Decision Brief selama demo ini; tindakan tersebut dapat menghasilkan notifikasi atau email. Jika demo harus mencakup alur perubahan data, matikan email pada API dan worker terlebih dahulu dengan persetujuan operator lokal.

## Kredensial dan data

- Gunakan hanya kredensial lokal yang sudah disimpan secara privat. Jangan menaruh password di repository, panduan, screenshot, atau pesan.
- Jangan menyalin `.env` atau kredensial ke GitHub.
- Jangan jalankan seed ulang: rapat sintetis demo sudah tersedia. Seed `backend.app.seed_demo_rapims` hanya ditujukan untuk database PostgreSQL lokal berakhiran `_dev` atau `_development`, tetapi membuat data baru dan tidak diperlukan untuk demo saat ini.
- Jangan gunakan data demo ini sebagai data resmi atau production.
- Jangan jalankan `docker compose down -v`; opsi tersebut menghapus volume database dan file lokal.

## Batasan

Demo ini berjalan hanya di komputer lokal dan tidak dapat diakses atasan dari internet. Ini bukan deployment production; kesiapan migrasi production, backup/restore, dan deployment belum diverifikasi.
