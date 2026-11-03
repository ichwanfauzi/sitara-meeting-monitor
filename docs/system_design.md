# SITARA — System Design (UI/UX)

**Versi:** 1.0-draft · **Tanggal:** 14 Oktober 2026  
**Status:** Fondasi visual untuk divalidasi sebelum implementasi seluruh halaman.

## 1. Sasaran desain

Antarmuka SITARA harus terasa profesional, tenang, teliti, dan mudah dipelajari untuk penggunaan internal pimpinan dan kesekretariatan. Desain mengutamakan kejelasan tanggung jawab, keputusan, tenggat, dan status, bukan ornamen visual.

Prinsip:

1. **Clarity before decoration:** keputusan, PIC, output, dan tenggat mudah ditemukan.
2. **Role-aware, not role-confusing:** navigasi mengikuti hak akses; jangan menampilkan menu yang tidak boleh dipakai.
3. **One source of truth:** informasi keputusan tampil dari data yang sama dan tidak diketik ulang di banyak tempat.
4. **Status is explicit:** setiap status ditulis dengan label dan ikon/penanda, bukan warna saja.
5. **Formal documents remain formal:** halaman web modern tidak mengubah format resmi dokumen hasil ekspor.
6. **Accessible by default:** fokus keyboard terlihat, kontras memadai, form berlabel, dan pesan error jelas.

## 2. Arah visual

Gunakan gaya **enterprise editorial**: latar netral, navigasi biru navy, aksen biru untuk tindakan utama, border halus, tabel rapat yang mudah dipindai, serta ruang kosong yang cukup. Hindari gradien berlebihan, efek glassmorphism, animasi yang tidak membantu, dan warna status yang terlalu dominan.

Warna berikut adalah token awal aplikasi, bukan klaim sebagai palet merek resmi ITPLN. Jika institusi memiliki panduan merek digital, panduan resmi tersebut harus menggantikannya.

### 2.1 Color tokens

| Token | Nilai | Penggunaan |
|---|---|---|
| `--color-brand-950` | `#14243A` | Sidebar/navy utama dan heading tertentu |
| `--color-brand-800` | `#203A5B` | Hover/aktif pada elemen brand |
| `--color-primary-700` | `#1D4ED8` | Tombol primer, tautan, fokus utama |
| `--color-primary-100` | `#DBEAFE` | Latar seleksi ringan |
| `--color-bg` | `#F5F7FA` | Latar aplikasi |
| `--color-surface` | `#FFFFFF` | Panel, tabel, dialog |
| `--color-border` | `#D9E0EA` | Border dan pemisah |
| `--color-text` | `#172033` | Teks utama |
| `--color-text-muted` | `#5B6678` | Teks sekunder |
| `--color-success` | `#166534` | Status sukses/selesai |
| `--color-warning` | `#92400E` | Peringatan dan menunggu Acc |
| `--color-danger` | `#B91C1C` | Kendala, aksi destruktif, error |
| `--color-info` | `#1D4ED8` | Informasi dan update |
| `--color-neutral` | `#475569` | Belum dimulai dan metadata netral |

### 2.2 Warna status tugas

| Status | Warna token | Label wajib |
|---|---|---|
| Belum Dimulai | `--color-neutral` | Belum Dimulai |
| Berproses | `--color-info` | Berproses |
| Terkendala | `--color-danger` | Terkendala |
| Menunggu Acc | `--color-warning` | Menunggu Acc |
| Selesai | `--color-success` | Selesai |

Label harus selalu terlihat. Pastikan teks pada badge memiliki kontras memadai; bila kombinasi warna tidak memenuhi target, gunakan latar status pucat dan teks gelap.

## 3. Tipografi

- **Font utama:** Inter dengan fallback `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- **Dokumen formal:** gunakan font yang ditentukan template resmi. Jangan mengasumsikan PDF harus menggunakan font UI.
- **Teks isi:** 14–16 px; line-height sekitar 1.45–1.65.
- **Label tabel/form:** 12–14 px, tidak terlalu tipis.
- **Judul halaman:** 24–28 px, weight 650–700.
- **Judul bagian:** 18–20 px, weight 600.
- **Angka KPI:** 26–32 px, gunakan angka tabular bila tersedia.
- **Metadata:** 12–13 px dengan kontras yang masih cukup.

Jangan menggunakan lebih dari dua keluarga font dalam aplikasi. Hindari menjadikan teks penting kecil hanya untuk menyesuaikan layout.

## 4. Spacing, bentuk, dan elevasi

Gunakan skala berbasis 4 px dengan kelipatan umum 8 px: `4, 8, 12, 16, 24, 32, 40, 48`. Border radius awal: 6 px untuk kontrol, 8 px untuk panel, 12 px untuk dialog/area penting. Gunakan border 1 px sebagai pemisah utama; shadow tipis hanya untuk menu melayang/dialog.

- Tinggi kontrol form/tombol standar: sekitar 40 px.
- Target sentuh mobile: usahakan 44 × 44 px atau lebih.
- Lebar konten desktop maksimum: sekitar 1440 px, dengan tabel luas boleh memakai ruang ekstra.
- Sidebar desktop: sekitar 240–256 px; dapat diciutkan jika diperlukan.
- Hindari panel berlapis dalam panel tanpa alasan informasi yang jelas.

## 5. Struktur aplikasi

### 5.1 Desktop

- **Sidebar kiri:** logo/nama SITARA, navigasi sesuai peran, status halaman aktif, dan menu akun.
- **Top bar:** breadcrumb/judul kontekstual, pencarian bila relevan, notifikasi, profil pengguna.
- **Area konten:** judul halaman, deskripsi singkat, tindakan utama, lalu data/komponen.
- **Feedback area:** toast untuk hasil tindakan, inline error untuk form, banner untuk masalah sesi atau koneksi.

### 5.2 Mobile/tablet

- Sidebar berubah menjadi drawer.
- Tabel lebar menyediakan horizontal scroll yang jelas atau tampilan daftar ringkas.
- Form panjang dibagi per bagian, tetapi jangan memaksa wizard jika pengguna perlu mengedit bebas.
- PIC harus dapat membuka tugas, membaca instruksi, memasukkan update, dan mengunggah bukti dari mobile.

## 6. Navigasi berdasarkan peran

Menu hanya dirender sesuai peran, tetapi pembatasan sebenarnya selalu dilakukan backend.

### Super Admin

- Ringkasan administrasi sistem
- Pengguna dan peran
- Unit dan hubungan organisasi
- Konfigurasi sistem
- Audit aktivitas administratif

### Sekretariat

- Dashboard monitoring menyeluruh
- Rapim dan notulensi
- Agenda dan pembahasan
- Putusan/action item
- Antrean verifikasi
- Decision Brief
- Repositori dokumen
- Notifikasi
- Statistik/laporan
- Audit log sesuai izin

### Rektor/Warek

- Dashboard lingkup tanggung jawab
- Rapim/notulensi yang diizinkan
- Decision Brief yang diizinkan
- Tugas dan disposisi bawahan
- Monitoring PIC
- Catatan dan notifikasi
- Dokumen tugas yang diizinkan

### PIC

- Dashboard tugas saya
- Daftar tugas
- Detail tugas
- Pembaruan progres dan kendala
- Bukti tugas
- Notifikasi

Tidak ada menu, breadcrumb, hasil pencarian, atau tombol untuk membuka notulen lengkap bagi PIC.

## 7. Halaman inti dan pola interaksi

### 7.1 Dashboard Sekretariat

- KPI: total tugas, selesai, berproses, terkendala, belum dimulai, menunggu Acc.
- Grafik hanya bila menjawab pertanyaan operasional yang jelas.
- Daftar tugas terlambat, belum diperbarui, atau menunggu verifikasi.
- Rekap rapat berdasarkan rentang tanggal/tahun.
- Filter yang dipilih harus terlihat dan mudah dihapus.
- Klik KPI menerapkan filter yang sesuai; hitungan harus berasal dari query/endpoint backend.

### 7.2 Dashboard Rektor/Warek

- Tugas dalam lingkup kewenangannya.
- Status/tenggat, tugas PIC aktif, kendala, dan update terbaru.
- Aksi cepat untuk membuka detail tugas atau mengirim catatan.
- Tidak ada tindakan untuk mengubah status resmi.

### 7.3 Dashboard PIC

- Fokus pada tugas sendiri: apa tugasnya, siapa pemberi tugas, output, tenggat, status resmi, progres, dan pembaruan terakhir.
- Prioritaskan tugas terlambat/terkendala tanpa memperlihatkan materi rapat terbatas.
- Tampilkan secara jelas cara mengirim progres dan bukti.

### 7.4 Live notulensi

Layout desktop disarankan memiliki:

- Panel navigasi agenda di kiri.
- Editor pembahasan/putusan di bagian tengah.
- Panel metadata di kanan untuk PIC, output, target, dan pilihan `Jadikan action item? Ya/Tidak`.
- Status penyimpanan eksplisit: `Menyimpan`, `Tersimpan`, atau `Gagal menyimpan`.
- Penanda notulis aktif dan status baca-saja bagi pengguna lain.
- Konfirmasi saat finalisasi; cegah penutupan halaman yang memiliki perubahan belum tersimpan.
- Nomor notulen manual; jangan menyisipkan generator nomor otomatis.

Meskipun disebut live, satu notulis adalah satu-satunya editor selama sesi live. Pengguna lain yang berwenang mendapat tampilan baca. Perubahan harus disimpan secara andal; notifikasi perubahan dapat menggunakan polling atau mekanisme push setelah kebutuhan teknis diputuskan.

Implementasi editor saat ini menampilkan field pembahasan dan putusan per agenda dan mengirim seluruh isi sebagai satu snapshot revisi. Snapshot teks versi lama tetap dapat dibaca; perpindahan ke format terstruktur tidak menetapkan teks lama ke agenda secara otomatis. Pengguna menyalin catatan ke agenda yang sesuai secara sadar. Putusan menyimpan teks, output yang diharapkan, target tanggal, dan penanda kebutuhan tindak lanjut. Backend Action Item memiliki API terpisah untuk pembuatan tugas, assignment, progres, dan bukti; workflow UI Action Item masih tahap berikutnya. API notulensi tetap tidak menerima identitas PIC untuk putusan; pengiriman field itu ditolak sebagai input tambahan.

### 7.5 Putusan dan detail action item

- Tampilkan konteks rapat/agenda/putusan yang relevan kepada pengguna yang berwenang.
- Field tugas: ringkasan, deskripsi, output yang diharapkan, PIC utama, PIC pendukung, target, prioritas, status resmi, update progres, dan bukti.
- Pisahkan **status resmi** dari **persentase/catatan progres**.
- PIC dapat mengirim pembaruan dan lampiran, tetapi tidak memiliki kontrol perubahan status resmi.
- Alasan revisi dari Sekretariat harus ditampilkan ke penerima tugas yang berwenang.

### 7.6 Decision Brief

- Hasil awal ditandai sebagai draf.
- Ringkasan berisi keputusan/perintah tindak lanjut, PIC, output, dan target.
- Sumber putusan dapat dibuka oleh pengguna yang berhak.
- Implementasi saat ini menyediakan pembacaan keputusan sumber, ringkasan editorial, label prioritas/catatan per keputusan, dan histori versi draf.
- Setiap versi mengacu pada ID revisi notulensi dan keputusan sumber yang tepat; perubahan revisi sumber menandai versi lama usang tanpa mengubah isi historis.
- Sekretariat dan pimpinan yang memiliki akses ke rapat dapat menyimpan versi draf. PIC dan Super Admin tidak dapat membaca Decision Brief.
- Persetujuan dan finalisasi menunggu penetapan kewenangan formal. Jangan menampilkan draf sebagai dokumen final.
- AI (jika kelak dipakai) membantu menyarankan konten; jangan finalisasi otomatis.

### 7.7 Repositori dan pencarian

- Filter tipe dokumen, rapat, tahun/tanggal, status final/draf, dan keyword.
- Metadata ditampilkan tanpa membocorkan isi dokumen yang tidak berhak dibaca pengguna.
- Semua unduhan melewati backend authorization; jangan memakai URL publik permanen.
- Arsip final memiliki versi, tanggal finalisasi, dan pelaku yang mengesahkan.

## 8. Komponen UI bersama

Komponen reusable yang disarankan:

- `AppShell`, `Sidebar`, `Topbar`, `Breadcrumbs`
- `PageHeader`, `PrimaryAction`, `FilterBar`, `SearchField`
- `KpiCard`, `StatusBadge`, `PriorityBadge`, `ProgressIndicator`
- `DataTable`, `Pagination`, `EmptyState`, `LoadingSkeleton`
- `FormField`, `DateField`, `SelectField`, `FileUpload`
- `ConfirmDialog`, `ReviewPanel`, `AuditTimeline`
- `NotificationBell`, `Toast`, `InlineAlert`
- `PermissionGate` untuk UX saja; bukan pengganti otorisasi backend.

Gunakan satu implementasi komponen status agar label dan warna konsisten. Jangan duplikasi logika izin di banyak komponen; gunakan helper izin terpusat untuk menentukan tampilan, sambil tetap memvalidasi akses di server.

## 9. Form, tabel, dan interaksi

- Setiap input punya label yang terlihat; placeholder bukan pengganti label.
- Error ditampilkan dekat field dan dirangkum bila form panjang.
- Tindakan destruktif/berdampak resmi harus membutuhkan konfirmasi yang jelas.
- Gunakan pagination dan filter server-side untuk data besar.
- Pertahankan pilihan filter saat pengguna kembali dari halaman detail bila memungkinkan.
- Bedakan tombol simpan draf, ajukan verifikasi, verifikasi, dan finalisasi.
- Jangan tampilkan tombol yang pengguna tidak berwenang gunakan, tetapi tetap anggap endpoint backend sebagai kontrol keamanan utama.

## 10. State wajib untuk setiap halaman

1. **Loading:** skeleton/spinner yang tidak menggeser layout berlebihan.
2. **Empty:** jelaskan mengapa belum ada data dan tindakan selanjutnya bila diizinkan.
3. **Error:** bahasa yang jelas, tanpa stack trace atau detail rahasia; sediakan coba lagi bila aman.
4. **Forbidden:** tampilkan akses tidak tersedia tanpa membocorkan apakah objek sensitif ada.
5. **Offline/timeout:** jelaskan bahwa perubahan belum pasti tersimpan dan sediakan cara retry.
6. **Unsaved changes:** beri peringatan sebelum navigasi/finalisasi jika ada perubahan belum tersimpan.
7. **Success:** pesan yang spesifik, misalnya `Bukti berhasil dikirim untuk diverifikasi`, bukan hanya `Sukses`.

## 11. Aksesibilitas

Target desain WCAG 2.2 AA. Minimal:

- Kontras teks normal 4.5:1 dan teks besar 3:1.
- Semua fungsi utama dapat dijalankan dengan keyboard.
- Focus indicator selalu terlihat.
- Status menggunakan teks/ikon selain warna.
- Form memiliki label dan error yang dapat dibaca screen reader.
- Dialog mengelola fokus dan dapat ditutup sesuai pola aksesibel.
- Jangan menggunakan animasi berkedip atau gerak yang tidak perlu; hormati reduced motion.

Validasi kontras token warna sebelum dipakai di komponen final; nilai token bukan bukti otomatis bahwa setiap kombinasi sudah memenuhi kontras.

## 12. Format dokumen resmi berbeda dari UI web

Ekspor notulen harus mempertahankan tampilan formal sesuai dokumen contoh yang disetujui: header/logo, identitas dan nomor notulen, data waktu/tempat, peserta, agenda, putusan/tindak lanjut, PIC, target, penutupan, blok pengesahan, dan nomor halaman jika diperlukan. Tabel panjang perlu mengulang header pada halaman berikutnya dan menghindari baris yang terpotong sebisa mungkin.

Template PDF harus divalidasi terhadap contoh resmi sebelum dianggap selesai. Jangan mengekspor halaman web dengan sidebar/KPI lalu menyebutnya sebagai notulen resmi.

## 13. Aturan implementasi visual

- Gunakan token CSS, bukan hardcode warna berbeda di setiap komponen.
- Mulai dari komponen sederhana, buat abstraction ketika pola benar-benar berulang.
- Jangan menambahkan animasi, chart, atau library UI hanya demi penampilan.
- Isi dashboard berasal dari data API; jangan menaruh angka contoh seolah data live.
- Gunakan data sintetis saat desain dan pengujian.
- Ikuti pola framework dan komponen yang telah dipilih di [`architecture.md`](./architecture.md).
