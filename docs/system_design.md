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

Penyegaran tampilan operasional berlaku untuk seluruh halaman selain Dashboard:
gunakan latar biru-abu yang lembut, pembeda visual antarbagian, dan panel kerja
berwarna netral agar formulir, daftar, serta status lebih mudah dipindai.

Warna berikut adalah token awal aplikasi, bukan klaim sebagai palet merek resmi ITPLN. Jika institusi memiliki panduan merek digital, panduan resmi tersebut harus menggantikannya.

### 2.1 Color tokens

| Token                 | Nilai     | Penggunaan                              |
| --------------------- | --------- | --------------------------------------- |
| `--color-brand-950`   | `#14243A` | Sidebar/navy utama dan heading tertentu |
| `--color-brand-800`   | `#203A5B` | Hover/aktif pada elemen brand           |
| `--color-primary-700` | `#1D4ED8` | Tombol primer, tautan, fokus utama      |
| `--color-primary-100` | `#DBEAFE` | Latar seleksi ringan                    |
| `--color-bg`          | `#F5F7FA` | Latar aplikasi                          |
| `--color-surface`     | `#FFFFFF` | Panel, tabel, dialog                    |
| `--color-border`      | `#D9E0EA` | Border dan pemisah                      |
| `--color-text`        | `#172033` | Teks utama                              |
| `--color-text-muted`  | `#5B6678` | Teks sekunder                           |
| `--color-success`     | `#166534` | Status sukses/selesai                   |
| `--color-warning`     | `#92400E` | Peringatan dan menunggu Acc             |
| `--color-danger`      | `#B91C1C` | Kendala, aksi destruktif, error         |
| `--color-info`        | `#1D4ED8` | Informasi dan update                    |
| `--color-neutral`     | `#475569` | Belum dimulai dan metadata netral       |

### 2.2 Warna status tugas

| Status        | Warna token       | Label wajib   |
| ------------- | ----------------- | ------------- |
| Belum Dimulai | `--color-neutral` | Belum Dimulai |
| Berproses     | `--color-info`    | Berproses     |
| Terkendala    | `--color-danger`  | Terkendala    |
| Menunggu Acc  | `--color-warning` | Menunggu Acc  |
| Selesai       | `--color-success` | Selesai       |

Label harus selalu terlihat. Pastikan teks pada badge memiliki kontras memadai; bila kombinasi warna tidak memenuhi target, gunakan latar status pucat dan teks gelap.

## 3. Tipografi

- **Font utama:** Inter dengan fallback `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- **Dokumen formal:** gunakan font yang ditentukan template resmi. Jangan mengasumsikan PDF harus menggunakan font UI.
- **Teks isi:** 14–16 px; line-height sekitar 1.45–1.65.
- **Label tabel/form:** 14–16 px, tidak terlalu tipis.
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
- **Top bar:** breadcrumb/judul kontekstual, pencarian bila relevan, pusat notifikasi dengan jumlah belum dibaca, dan profil pengguna. Panel notifikasi menampilkan pesan generik, waktu, tautan objek, serta aksi tandai dibaca.
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
- Akses baca ke seluruh Rapim, notulen, dan Decision Brief
- Pemantauan lintas Rapim dan tindak lanjut
- Rapim dan notulensi
- Agenda dan pembahasan
- Putusan/action item
- Antrean verifikasi
- Decision Brief
- Repositori dokumen
- Notifikasi
- Statistik/laporan
- Audit log sesuai izin

### Manager Legal

- Beranda dengan tombol utama Buat Rapat dan Tambah Agenda
- Pembuatan dan pengelolaan rapat, agenda, notulensi, dan Decision Brief
- Pembuatan dan pengelolaan tindak lanjut bersama Sekretariat
- Kontrol status rapat, status resmi tugas, dan verifikasi penyelesaian yang sama dengan Sekretariat

### Rektor/Warek

- **Rektor:** beranda pantau baca saja untuk seluruh rapat, notulensi, Decision Brief, dan tindak lanjut; tidak ada tombol buat/edit.
- **Warek:** dapat membuat dan mengelola rapat, agenda, dan notulensi; dapat membaca Decision Brief dan memantau tindak lanjut, tanpa tombol membuat tindak lanjut.
- Kedua peran dapat membaca seluruh Rapim dan dokumennya.

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

- Hilangkan judul/panel “Ringkasan operasional”.
- Tampilkan tombol yang mudah ditemukan untuk **Buat Rapat** dan **Tambah Agenda** tepat setelah login.
- Pakai nama tombol dan petunjuk berbahasa sederhana, teks yang terbaca, dan formulir ringkas untuk pengguna yang tidak sehari-hari memakai aplikasi.
- KPI: total tugas, selesai, berproses, terkendala, belum dimulai, menunggu Acc.
- Grafik hanya bila menjawab pertanyaan operasional yang jelas.
- Daftar tugas terlambat, belum diperbarui, atau menunggu verifikasi.
- Rekap rapat berdasarkan rentang tanggal/tahun.
- Filter yang dipilih harus terlihat dan mudah dihapus.
- Klik KPI menerapkan filter yang sesuai; hitungan harus berasal dari query/endpoint backend.

### 7.2 Dashboard Rektor/Warek

- **Rektor:** pemantauan baca saja atas seluruh Rapim, notulensi, Decision Brief, dan tindak lanjut; tanpa tombol buat atau edit.
- **Warek:** akses rapat, agenda, dan notulensi; dapat memantau tindak lanjut, tetapi tidak membuat tugas baru.
- Status tugas dan tenggat memakai label teks yang jelas; jangan hanya membedakan lewat warna.

### 7.3 Dashboard PIC

- Fokus pada tugas sendiri: apa tugasnya, siapa pemberi tugas, output, tenggat, status resmi, progres, dan pembaruan terakhir.
- Prioritaskan tugas terlambat/terkendala tanpa memperlihatkan materi rapat terbatas.
- Tampilkan secara jelas cara mengirim progres dan bukti.

### 7.4 Live notulensi

Gunakan area desktop yang nyaman dibaca. Ringkasan rapat dan agenda ditampilkan ringkas
di bagian atas. Form pengisian disusun vertikal per agenda: pokok bahasan terlebih dahulu,
lalu putusan/arahan dan rencana tindak lanjut opsional di dalam kartu yang sama. Jangan
mengharuskan pengguna menggeser tabel lebar untuk mengisi teks. Sediakan ruang yang cukup
untuk uraian panjang dan kontrol yang mudah dipilih. Pratinjau hasil akhir tetap memakai
tabel tersendiri dan dicetak dalam format landscape.

- Status penyimpanan eksplisit: `Menyimpan`, `Tersimpan`, atau `Gagal menyimpan`.
- Status penyimpanan yang terlihat bagi semua editor inti.
- Konfirmasi saat finalisasi; cegah penutupan halaman yang memiliki perubahan belum tersimpan.
- Nomor agenda otomatis; peserta dipilih dari daftar pengguna, tanpa field jabatan atau status kehadiran.
- SITARA tidak menyediakan input audio, pemutar rekaman, atau kolom transkripsi. Hasil rapat yang telah disiapkan dimasukkan dan ditinjau manusia pada tabel notulensi terstruktur; integrasi AI eksternal belum tersedia.
- Riwayat revisi dan identitas pembuat tidak ditampilkan pada editor operasional; akses teknis DBA tetap melalui jalur administrasi.

Selama sesi LIVE, pengguna aktif Sekretariat, Manager Legal, Rektor, dan Warek dapat mengedit notulensi. Notulis opsional dipilih saat rapat dibuat untuk atribusi, bukan sebagai gerbang edit. Setiap editor mengirim revisi lengkap dengan `base_revision_id`; revisi usang ditolak agar tidak menimpa perubahan yang lebih baru. Kolaborasi real-time belum tersedia.

Form editor mengelompokkan pokok bahasan, putusan/arahan, PIC usulan, PIC pendukung opsional,
output, dan target
secara berurutan di dalam kartu agenda. Seluruh isi tetap dikirim sebagai satu snapshot
revisi terstruktur. Revisi teks lama tetap tersimpan; isinya tidak disalin atau dipetakan
ke agenda secara otomatis. Detail PIC, output, dan target hanya ditampilkan setelah putusan
ditandai memerlukan tindak lanjut.
Setiap pokok pembahasan memakai satu baris visual; beberapa putusan ditampilkan sebagai
daftar bernomor di dalam baris yang sama. Nomor hanya ditampilkan pada putusan; PIC, Output,
dan Target di kolom masing-masing tidak diberi nomor berulang. Target penyelesaian dapat diisi
sebagai tanggal atau teks manual. Pratinjau cetak mengikuti notula formal landscape dan
menambahkan kolom nomor.
Pengguna inti yang menyunting mencatat teks putusan, PIC usulan, PIC pendukung opsional, output,
target tanggal atau teks, dan penanda kebutuhan tindak lanjut. Kedua kolom PIC pada notulen
adalah teks bebas, bukan identitas atau assignment resmi. Riwayat teknis revisi tidak ditampilkan
di editor.

### 7.5 Putusan dan detail action item

- Tampilkan konteks rapat/agenda/putusan yang relevan kepada pengguna yang berwenang.
- Field tugas: ringkasan, deskripsi, output yang diharapkan, PIC utama, PIC pendukung, target, prioritas, status resmi, update progres, dan bukti.
- Pilih PIC utama dan pendukung dari daftar pengguna inti berdasarkan jabatan; sediakan pilihan `Lainnya` untuk nama/jabatan di luar daftar. Tampilkan jabatan dan peran assignment, tanpa kolom pencarian PIC terpisah.
- PIC utama dan pendukung dapat diisi berdampingan saat membuat tindak lanjut; detail menampilkan pasangan jabatan dan perannya, misalnya `Wakil Rektor I · PIC pendukung`.
- Halaman awal Tindak Lanjut memakai pola hero, pencarian, dan panel hasil yang sama dengan menu Rapat. Tampilkan tombol Buat Tindak Lanjut dan daftar tugas tanpa detail panjang; kartu menonjolkan judul/tenggat serta label status di sisi kanan. Saat tombol pembuatan dipilih, form menggantikan daftar; tombol kembali membawa pengguna ke daftar.
- Memilih tugas membuka detail dalam dialog dengan latar belakang buram. Daftar tugas menampilkan judul dan status; detail, progres, bukti, dan PIC lengkap tetap berada di dialog.
- Sekretariat/Manager Legal dapat mengedit atau mengeluarkan tugas aktif dari daftar. Pengaturan PIC ditempatkan dalam panel Edit. Menghapus berarti soft delete agar progres, bukti, assignment, dan audit tetap tersimpan.
- Daftar Tindak Lanjut aktif tidak menampilkan tugas berstatus `SELESAI`; tugas selesai ditemukan di Repository.
- Pengakhiran penugasan PIC pendukung oleh Sekretariat atau Manager Legal memerlukan dua konfirmasi berurutan sebelum permintaan dikirim.
- Pisahkan **status resmi** dari **persentase/catatan progres**.
- PIC dapat mengirim pembaruan dan lampiran, tetapi tidak memiliki kontrol perubahan status resmi.
- Alasan revisi dari Sekretariat harus ditampilkan ke penerima tugas yang berwenang.

### 7.6 Decision Brief

- Hasil awal ditandai sebagai draf.
- Form editor menggunakan lebar halaman dan tabel No., Bahasan, Putusan/Tindak Lanjut, PIC, Output, dan Target Penyelesaian. Putusan/Tindak Lanjut diisi sebagai ringkasan baru; Bahasan, PIC, Output, dan Target diprefill dari revisi notulensi sumber tanpa menyalin putusan lengkap.
- Pratinjau/cetak memakai tabel landscape dan judul Decision Brief Rapim bertanggal; baris putusan wajib diisi sebelum menyimpan versi draf.
- Setiap versi tetap terikat pada notulensi sumbernya, bukan pada isi notulensi yang lebih baru.
- Sumber putusan dapat dibuka oleh pengguna yang berhak.
- Setiap putusan pada revisi sumber harus tercantum dalam Decision Brief yang terhubung ke rapat dan revisi tersebut.
- Histori versi dan workflow approval tetap terikat pada revisi sumber. Data ringkasan/prioritas/catatan dari versi lama tetap terbaca dari arsip, tetapi form baru memakai satu kolom ringkasan putusan/tindak lanjut.
- Setiap versi mengacu pada ID revisi notulensi dan keputusan sumber yang tepat; perubahan revisi sumber menandai versi lama usang tanpa mengubah isi historis.
- Pengajuan hanya tersedia setelah rapat `FINAL` dan review `VALID` untuk revisi sumber yang tepat. Pembuat versi atau pejabat approver (Rektor/Warek/Sekretariat/Manager Legal) dalam scope dapat mengajukan; pembuat tidak dapat menyetujui versinya sendiri, penolakan wajib beralasan, dan hanya pembuat yang dapat menarik pengajuan saat pending.
- PIC dan Super Admin tidak dapat membaca Decision Brief. Status dan histori approval berasal dari event append-only; koreksi konten harus menjadi versi baru.
- PostgreSQL 16 concurrency/integrity telah diverifikasi pada target disposable di Stage 19; browser E2E belum dijalankan. Formal publication/finalisasi dokumen setelah approval belum tersedia; jangan menampilkan brief sebagai dokumen final.
- AI (jika kelak dipakai) membantu menyarankan konten; jangan finalisasi otomatis.

### 7.7 Repositori dan pencarian

- Filter tipe dokumen, rapat, tahun/tanggal, status final/draf, dan keyword.
- Metadata ditampilkan tanpa membocorkan isi dokumen yang tidak berhak dibaca pengguna.
- Semua unduhan melewati backend authorization; jangan memakai URL publik permanen.
- Arsip final memiliki versi, tanggal finalisasi, dan pelaku yang mengesahkan.
- Halaman awal menu **Repository** memakai pola hero, pencarian, dan panel hasil yang sama dengan menu Rapat; daftar rapat tetap memiliki filter status dan bulan. Setelah rapat dipilih, halaman detail menampilkan agenda, notulensi, Decision Brief, dan tindak lanjut terkait dalam kelompok terpisah. PIC tetap memakai menu Tugas Saya dan tidak mendapat akses ke notulensi/Decision Brief; tindak lanjut yang tampil mengikuti cakupan akses API.
- Halaman awal Rapat, Notulensi, Decision Brief, Tindak Lanjut, dan Repository memakai lebar konten yang konsisten serta pola hero/pencarian/hasil. Kartu daftar memakai dua kolom pada desktop dan beralih menjadi satu kolom pada layar sempit.
- PIC melihat pengingat di dashboard untuk tugas sendiri yang sudah lewat tenggat atau jatuh tempo dalam tujuh hari. Pengingat ini hanya tampil dalam aplikasi; tidak mengirim email atau menghubungi layanan eksternal.
- Halaman awal menu Notulensi dan Decision Brief memakai daftar Rapim yang bisa dicari dan dipaginasi. Memilih Rapim langsung membuka fungsi pengisian yang sesuai.
- Pemilih Rapim saat membuat Tindak Lanjut memakai pencarian teks dan hasil bertahap, bukan daftar panjang yang harus di-scroll.
- Dashboard tidak menampilkan daftar Rapim terbaru. Kartu tindak lanjut ringkas menampilkan judul, status, dan PIC; klik kartu membuka detail dalam dialog yang sama seperti menu Tindak Lanjut. Tombol Lainnya menampilkan tugas berikutnya.

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
- Gunakan teks utama sedikitnya 14 px, label yang jelas, tombol dengan area tekan sedikitnya 44 px, dan jarak antar tindakan agar nyaman dibaca serta dipilih.
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
