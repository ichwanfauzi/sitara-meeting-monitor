# Product Requirements Document (PRD) — SITARA
**Produk:** SITARA — Sistem Informasi Tindak Lanjut Rapat dan Arahan
**Versi dokumen:** 1.0-draft  
**Tanggal:** 14 Oktober 2026  
**Status:** Draft untuk validasi pemilik proses  
**Pemilik proses utama:** Direktorat Kesekretariatan  
**Target pengguna:** tujuh pengguna inti yang direncanakan: Rektor, empat Warek, Direktur Sekretariat, dan Manager Legal; Super Admin teknis terpisah. PIC tindak lanjut dipilih dari pengguna inti atau dicatat sebagai nama bebas.
> Dokumen ini mengubah kebutuhan yang telah disampaikan menjadi kebutuhan produk yang dapat dirancang, dibangun, dan diuji. Ketentuan administrasi yang belum dikonfirmasi ditandai sebagai asumsi atau keputusan terbuka; jangan menganggapnya sebagai kebijakan institusi final.

## 1. Ringkasan produk

SITARA adalah aplikasi web internal untuk membantu Direktorat Kesekretariatan mengelola hasil Rapat Pimpinan (Rapim), mencatat pembahasan dan putusan, menghasilkan draf Decision Brief, mendistribusikan tindak lanjut, memantau progres, memverifikasi bukti penyelesaian, dan menyimpan dokumen final dalam repositori terstruktur.

SITARA menggunakan satu sumber data terstruktur. Informasi yang dimasukkan saat rapat digunakan kembali untuk notulen, Decision Brief, action item, notifikasi, laporan, dan arsip sehingga mengurangi pencatatan berulang.

## 2. Masalah yang ingin diselesaikan

1. Hasil rapat, keputusan, dan tugas berisiko dicatat berulang kali di dokumen yang berbeda.
2. Satu rapat menghasilkan banyak putusan, tetapi progres tindak lanjut tiap putusan atau tugas dapat berbeda dan sulit dipantau apabila hanya tersimpan sebagai tabel dokumen.
3. Distribusi keputusan dan tindak lanjut kepada PIC perlu mengikuti tanggung jawab yang jelas.
4. Pihak yang berbeda membutuhkan tampilan dan akses berbeda. PIC tidak boleh membaca notulen atau Decision Brief lengkap yang terbatas.
5. Status tugas, pembaruan progres, bukti, dan verifikasi perlu dapat ditelusuri.
6. Dokumen agenda, bahan rapat, notulen, Decision Brief, dan bukti tindak lanjut membutuhkan repositori yang mudah dicari.
7. Pengelolaan manual menyulitkan rekap jumlah rapat, status tugas, keterlambatan, dan tingkat penyelesaian.
8. Notulen dan Decision Brief perlu diekspor mengikuti format administrasi resmi, bukan sekadar dicetak dari tampilan dashboard.

## 3. Tujuan produk

- Mencatat notulensi Rapim saat LIVE; pengguna aktif Sekretariat, Manager Legal, Rektor, dan Warek dapat mengedit dengan kontrol konflik revisi.
- Mengelola hasil rapat dalam tabel notulensi terstruktur. SITARA tidak merekam atau mengunggah audio; poin yang sudah disiapkan di luar SITARA dimasukkan dan ditinjau manusia sebelum menjadi notulensi resmi. Integrasi AI eksternal belum tersedia.
- Menjadikan notulen terstruktur sebagai sumber untuk Decision Brief, action item, monitoring, ekspor, dan arsip.
- Mendukung keputusan yang tidak membutuhkan tindak lanjut tanpa membuat tugas secara otomatis.
- Memberi setiap tugas PIC utama, PIC pendukung bila diperlukan, output yang diharapkan, tenggat, riwayat progres, dan bukti.
- Menegakkan aturan status resmi: Sekretariat dan Manager Legal berwenang yang boleh mengubah status tugas dan memverifikasi penyelesaian.
- Membatasi akses menurut peran, hubungan tanggung jawab, dan objek yang sedang diakses.
- Menyediakan audit log, notifikasi, pencarian, dan statistik operasional.
- Mengurangi pekerjaan administratif berulang serta membantu distribusi draf Decision Brief sesuai sasaran H+1 yang tercantum dalam materi strategi Rapim, dengan tetap mengikuti persetujuan dan SOP resmi.

## 4. Bukan tujuan (non-goals) versi awal

- Menggantikan seluruh sistem akademik, kepegawaian, atau aplikasi institusi lain.
- Membuka akses aplikasi kepada publik atau pihak eksternal secara default.
- Menjadikan hasil AI sebagai putusan atau dokumen resmi tanpa pemeriksaan manusia.
- Membiarkan AI mengubah status resmi, menetapkan persetujuan, atau menandatangani dokumen.
- Menganggap hasil OCR sebagai data akurat tanpa konfirmasi pengguna.
- Membangun microservices atau infrastruktur cloud yang berlebihan untuk aplikasi tahap awal.

## 5. Aktor dan kebutuhan mereka

### 5.1 Super Admin

Aktor teknis yang dikelola secara terpisah dari akun operasional Sekretariat. Bertugas mengelola konfigurasi sistem dan administrasi akun/peran sesuai kebijakan. Hak teknis Super Admin tidak otomatis memberi wewenang operasional untuk mengubah status tugas atau menyetujui hasil. Tindakan administratif istimewa harus diaudit.

### 5.2 Sekretariat

- Membuat dan mengelola metadata rapat serta notulensi.
- Membaca semua Rapim, notulen, dan Decision Brief.
- Mengedit notulen selama sesi LIVE bersama Manager Legal dan Warek.
- Mengelola putusan, action item, distribusi, catatan, arsip, dan draf Decision Brief.
- Memverifikasi pengajuan hasil dari PIC/pimpinan dan mengubah status resmi tugas bersama Manager Legal.
- Menjadi pemilik pemantauan lintas Rapim dan tindak lanjut.

### 5.3 Manager Legal

- Membuat dan mengelola rapat, agenda, notulensi, dan Decision Brief.
- Membuat tindak lanjut dan mengelola metadata/assignment bersama Sekretariat.
- Memiliki kewenangan operasional yang sama dengan Sekretariat, termasuk mengubah status rapat dan tugas serta memverifikasi penyelesaian. Akses teknis Super Admin tetap terpisah.

### 5.4 Rektor

- Membaca semua Rapim, notulen, dan Decision Brief.
- Memantau seluruh rapat, notulensi, Decision Brief, dan tindak lanjut dalam mode baca saja.
- Tidak membuat atau mengubah rapat, notulensi, maupun tindak lanjut.

### 5.5 Wakil Rektor (Warek)

- Membaca semua Rapim, notulen, dan Decision Brief.
- Membuat dan mengelola rapat, agenda, dan notulensi; mengedit notulensi saat LIVE.
- Membaca Decision Brief dan memantau tindak lanjut.
- Tidak membuat atau mengelola metadata/assignment tindak lanjut; jika ditetapkan sebagai PIC, Warek dapat mengirim laporan progres.

### 5.6 PIC tugas

- Melihat tugas yang ditugaskan kepadanya, instruksi, output, target waktu, pembaruan terkait, dan dokumen yang diizinkan.
- Mengirim pembaruan progres, melaporkan kendala, serta mengunggah bukti.
- Tidak dapat melihat notulen lengkap atau Decision Brief terbatas.
- Tidak dapat mengubah status resmi tugas.

## 6. Proses bisnis utama

1. Sekretariat, Manager Legal, dan Warek dapat membuat rapat. Nomor rapat dapat diubah kapan saja oleh peran pengelola rapat; perubahan metadata lain hanya saat `DRAFT` atau `LIVE`. Status rapat dikelola Sekretariat atau Manager Legal.
2. Agenda diberi nomor otomatis. Peserta dapat dipilih dari daftar pengguna aktif atau ditambahkan sebagai peserta lainnya dengan nama saja; peserta lainnya tidak mendapat akun atau akses SITARA. Formulir tidak meminta ID atau status kehadiran. PIC dan PIC pendukung agenda adalah teks usulan.
3. Saat status rapat `LIVE`, pengguna aktif Sekretariat, Manager Legal, Rektor, dan Warek dapat mengedit isi notulen. Identitas notulis dapat dipilih saat rapat dibuat untuk atribusi, tetapi bukan gerbang hak edit dan tidak ada serah terima notulis. Pengiriman `base_revision_id` mencegah revisi usang menimpa perubahan terbaru.
4. Pengguna inti yang menyunting notulen memasukkan agenda, pembahasan, putusan/arahan, PIC yang disarankan, output, dan target penyelesaian.
5. Untuk setiap putusan, pengguna memilih `apakah_menjadi_action_item` (`Ya`/`Tidak`). `Tidak` berarti putusan tetap disimpan sebagai bagian notulen tetapi tidak membuat tugas. `Ya` memungkinkan pembuatan satu atau lebih action item.
6. Sekretariat dan Manager Legal dapat membuat tindak lanjut, mengelola metadata/assignment, mengubah status resmi, dan memverifikasi penyelesaian. PIC dipilih dari tujuh pengguna inti aktif (Sekretariat, Manager Legal, Rektor, dan empat Warek) yang memiliki keanggotaan unit aktif; Rektor/Warek dapat menjadi PIC tetapi tidak dapat membuat atau menetapkan tindak lanjut. Tidak ada akun PIC tambahan di roster operasional. Pengguna yang ditetapkan sebagai PIC dapat mengirim progres; PIC dan Super Admin tidak dapat mengubah status resmi atau mewarisi kewenangan pengelola pada akun campuran. Unit penanggung jawab tugas tidak wajib; data unit yang sudah tercatat tetap dipertahankan. PIC akun memilih unit asal dari keanggotaannya; PIC nama bebas tetap dapat digunakan tanpa unit asal terverifikasi. Alasan assignment bersifat opsional dan tidak dimasukkan ke audit umum. Tindak lanjut dapat terhubung ke disposisi hanya jika sumber putusan dan revisinya sama.
7. Setiap putusan sumber dicantumkan pada Decision Brief yang terhubung ke rapat dan revisi notulensi yang tepat. Ringkasan editorial tidak menggantikan notulensi.
8. SITARA tidak menerima atau mengunggah rekaman rapat. Integrasi AI eksternal memerlukan persetujuan institusi; hasil yang dimasukkan ke SITARA tetap harus diperiksa manusia.
9. PIC yang memiliki akses dapat mengirim update progres, catatan, kendala, serta bukti. Update tidak otomatis mengubah status resmi.
10. Sekretariat atau Manager Legal memeriksa pengajuan penyelesaian. Jika bukti perlu diperbaiki, mereka mencatat alasan dan status yang sesuai. Jika hasil diverifikasi, mereka menetapkan status `SELESAI`.
11. Dokumen final, bukti dan catatan tindak lanjut masuk repositori dengan hak akses tetap berlaku.
12. Dashboard dan laporan menghitung data dari sumber terstruktur, bukan angka yang diketik terpisah.

## 7. Persyaratan fungsional

Prioritas: **P0** = wajib untuk MVP; **P1** = setelah alur inti berjalan; **P2** = peningkatan berikutnya.

| ID | Prioritas | Persyaratan | Kriteria penerimaan ringkas |
|---|---|---|---|
| FR-001 | P0 | Autentikasi | Pengguna aktif dapat login/logout; kredensial salah dan akun nonaktif ditolak. |
| FR-002 | P0 | RBAC dan pembatasan objek | API memeriksa peran dan kewenangan atas setiap objek; akses terlarang ditolak di server. |
| FR-003 | P0 | Manajemen rapat | Pengguna berwenang dapat membuat, memperbarui metadata, mengelola peserta pengguna, dan mencatat peserta non-pengguna sebagai nama tanpa memberi akses SITARA. |
| FR-004 | P0 | Nomor rapat | Nomor unik dapat diubah oleh pengelola rapat pada semua status. |
| FR-005 | P0 | Agenda dan pembahasan | Nomor agenda otomatis; tiap agenda memiliki PIC/PIC pendukung bebas serta beberapa pembahasan dan putusan. |
| FR-006 | P0 | Edit notulensi saat live | Sekretariat, Manager Legal, Rektor, dan Warek dapat mengedit notulen LIVE; konflik revisi tidak menimpa data terbaru. |
| FR-007 | P0 | Putusan menjadi action item | Untuk setiap putusan tersedia pilihan Ya/Tidak; `Tidak` tidak membuat tugas. |
| FR-008 | P0 | Penugasan | Action item memiliki PIC utama (akun inti atau nama bebas), PIC pendukung, output, dan tenggat. Hanya Sekretariat dan Manager Legal yang membuat tindak lanjut. |
| FR-009 | P0 | Status resmi | Sekretariat dan Manager Legal aktif dapat mengubah status resmi; setiap transisi tercatat. PIC dan Super Admin tetap ditolak. |
| FR-010 | P0 | Pembaruan progres | PIC/pimpinan terkait dapat mengirim update dan kendala tanpa mengubah status resmi. |
| FR-011 | P0 | Bukti dan verifikasi | PIC dapat mengunggah bukti pada tugas sendiri; Sekretariat atau Manager Legal dapat meninjau dan meminta revisi. |
| FR-012 | P0 | Audit log | Perubahan sensitif mencatat pelaku, waktu, objek, tindakan, dan data perubahan yang aman disimpan. |
| FR-013 | P0 | Decision Brief | Setiap putusan pada notulensi sumber dicantumkan dalam Decision Brief terkait rapat dan revisi yang tepat; draf ditinjau sebelum final. |
| FR-014 | P1 | Repositori | Halaman awal Repository hanya menampilkan daftar rapat FINAL/ARCHIVED. Setelah rapat dipilih, tampilkan agenda, notulensi, Decision Brief, dan tindak lanjut yang terkait sesuai akses pengguna. |
| FR-015 | P1 | Notifikasi | PIC/reviewer menerima notifikasi in-app untuk peristiwa terkait; email generik opsional hanya dikirim kepada pihak terkait saat diaktifkan. Pengingat tenggat otomatis untuk tugas sendiri yang lewat tenggat atau jatuh tempo dalam tujuh hari tetap menjadi kebutuhan lanjutan. |
| FR-016 | P1 | Ekspor PDF/tabel | Hasil ekspor memakai template yang disetujui dan menghormati izin akses. |
| FR-017 | P1 | Pencarian dan filter | Daftar rapat Repository dapat difilter menurut kata kunci, tahun, dan status rapat sesuai peran. |
| FR-018 | P1 | Dashboard dan rekap | Statistik rapat/tugas dapat difilter dengan data yang sumbernya dapat ditelusuri. |
| FR-019 | P2 | OCR/digitasi | File PDF/gambar dapat diekstrak menjadi draf teks yang dapat diperiksa sebelum disimpan. |
| FR-020 | P2 | Bantuan AI | AI dapat membuat usulan ringkasan/Decision Brief; pengguna berwenang harus meninjau sebelum final. |

## 8. Aturan bisnis wajib

1. Peran resmi mencakup `SUPER_ADMIN`, `SEKRETARIAT`, `MANAGER_LEGAL`, `REKTOR`, `WAREK`, dan `PIC`.
2. Super Admin dan Sekretariat adalah identitas peran yang berbeda.
3. Pengguna aktif Sekretariat, Manager Legal, Rektor, dan Warek dapat membaca semua metadata Rapim, notulen penuh, dan Decision Brief. PIC dan Super Admin tidak mendapatkannya, termasuk melalui URL langsung, API, ID yang dimanipulasi, pencarian, ekspor, atau URL penyimpanan; batas ini tetap berlaku pada akun campuran.
4. Saat rapat berstatus LIVE, Sekretariat, Manager Legal, Rektor, dan Warek dapat mengedit notulen. Hak edit diperiksa backend; revisi usang ditolak melalui kontrol versi. Hak ini tidak memperluas kewenangan mengubah metadata rapat.
5. Status resmi tugas hanya boleh diubah oleh pengguna Sekretariat atau Manager Legal yang berwenang. Pembatasan berlaku di API dan perlu didukung kontrol database yang sesuai.
6. Lima status resmi: `BELUM_DIMULAI`, `BERPROSES`, `TERKENDALA`, `MENUNGGU_ACC`, `SELESAI`.
7. `SELESAI` hanya boleh ditetapkan setelah hasil diverifikasi oleh Sekretariat atau Manager Legal dan record verifikasi disimpan.
8. Putusan yang tidak menjadi action item tetap tersimpan di notulen dan tidak membuat tugas.
9. Satu putusan boleh menghasilkan beberapa action item; setiap tugas dapat memiliki satu PIC utama aktif dan satu atau lebih PIC pendukung.
10. Hanya Sekretariat dan Manager Legal aktif tanpa `SUPER_ADMIN` dapat membuat atau mengelola tindak lanjut. PIC utama/pendukung dipilih dari pengguna inti aktif atau dicatat sebagai nama bebas; jangan mewajibkan unit atau alasan penugasan. Mereka dapat mengedit atau mengeluarkan tugas aktif dari daftar; penghapusan bersifat lunak dan mempertahankan assignment, progres, status, bukti, serta audit. Tugas `SELESAI` hanya dibaca dari Repository.
11. Nomor rapat dapat diperbarui oleh Sekretariat, Manager Legal, dan Warek pada setiap status dengan kontrol versi dan audit. Status rapat dikelola Sekretariat atau Manager Legal.
12. Dokumen bersifat privat secara default. `storage_key` tidak boleh dikirim ke klien yang tidak berwenang.
13. Finalisasi/revisi dokumen harus mempertahankan versi dan riwayat. Dokumen resmi tidak boleh diam-diam ditimpa.
14. Setiap pemeriksaan notulensi mengacu pada satu revisi tertentu. Revisi baru membuat pemeriksaan lama tidak berlaku untuk finalisasi; hanya pemeriksaan terbaru yang `VALID` pada revisi aktif yang dapat memenuhi syarat `LIVE → FINAL`.
14. Setiap ekspor dokumen terbatas harus melalui pemeriksaan akses dan dicatat pada audit log.
15. Tidak ada aksi AI yang boleh mengubah status tugas atau mengesahkan dokumen secara otomatis.
16. Decision Brief hanya dapat diajukan setelah rapat `FINAL` dan notulensi sumber memiliki review `VALID`. Pengguna aktif dalam cakupan rapat dengan role Sekretariat, Manager Legal, Rektor, atau Warek dapat menyetujui/menolak versi yang diajukan, tetapi tidak dapat meninjau versi yang dibuatnya sendiri. PIC dan Super Admin tidak berwenang.
17. Peserta rapat yang bukan pengguna SITARA dicatat sebagai nama eksternal terpisah dari akun pengguna; catatan ini tidak membuat akun, peran, atau akses aplikasi.

## 9. Model status tugas

- `BELUM_DIMULAI`: tugas ada, pelaksanaan belum mulai.
- `BERPROSES`: pelaksanaan sedang berlangsung.
- `TERKENDALA`: ada hambatan yang perlu ditangani atau dieskalasikan.
- `MENUNGGU_ACC`: hasil diajukan dan menunggu pemeriksaan Sekretariat.
- `SELESAI`: hasil diverifikasi dan status ditetapkan Sekretariat.

Update progres (termasuk persentase jika dipakai) terpisah dari status resmi. Definisi rumus progres dashboard harus dikunci sebelum dashboard statistik dibuat. Jangan menyamakan rata-rata persentase dengan proporsi jumlah tugas selesai tanpa label yang benar.

## 10. Dokumen, ekspor, digitasi, dan AI

- Notulen resmi memakai formulir dan hasil cetak tabel landscape dengan kolom Agenda/Pokok Bahasan, Putusan/Arahan & Tindak Lanjut, PIC, PIC pendukung, dan Target; area teks putusan harus cukup luas untuk uraian panjang. Output tabel menjadi bagian tersendiri.
- PIC pada notulen adalah PIC usulan berbentuk teks; PIC pendukung bersifat opsional dan juga berupa teks bebas. Penugasan resmi tetap dibuat sebagai Action Item agar satu putusan dapat memiliki beberapa tugas dan setiap assignment memiliki riwayat tersendiri.
- Revisi notulen lama berbentuk teks harus tetap terpelihara dan dapat dibuka sebagai sumber baca. Sistem tidak memetakan catatan lama ke kolom tabel tanpa tindakan pengguna.
- Tidak ada input audio, pemutar rekaman, atau kolom transkripsi terpisah di SITARA. Editor memasukkan hasil yang telah disiapkan ke tabel notulensi dan meninjau setiap pembahasan serta putusan.
- Template PDF final perlu diuji untuk tabel multi-halaman, header tabel berulang, nomor halaman, ukuran kertas, margin, dan pemisahan tanda tangan. Isi persis blok pengesahan mengikuti template resmi yang disetujui.
- Decision Brief merupakan ringkasan keputusan/tindak lanjut (misalnya keputusan/perintah, PIC, PIC pendukung, output, target). Pratinjau dan cetaknya mengikuti format contoh: judul Decision Brief Rapim bertanggal dan tabel No., Bahasan, Putusan/Tindak Lanjut, PIC, PIC pendukung, Output, serta Target Penyelesaian. Setiap versi mengambil PIC, PIC pendukung, output, dan target dari revisi notulensi sumber yang tepat. Notulen tetap menjadi rekam rapat lengkap; versi Decision Brief tetap menunjukkan status draf/persetujuannya.
- Kolom Putusan/Tindak Lanjut pada Decision Brief diisi tersendiri sebagai ringkasan singkat; Bahasan, PIC, Output, dan Target diprefill dari revisi notulensi yang menjadi sumber. Teks putusan lengkap tetap berada di notulensi.
- OCR hanya menghasilkan draf hasil ekstraksi. Pengguna perlu mengonfirmasi teks, nomor, tanggal, PIC dan tenggat yang terbaca.
- AI, bila diaktifkan, hanya menghasilkan draf/ususlan; jangan mengirim dokumen terbatas ke penyedia eksternal sebelum disetujui institusi dan disiapkan kontrol privasinya.

## 11. Persyaratan nonfungsional

- **Keamanan:** HTTPS di lingkungan yang diakses melalui jaringan; password hash kuat; secret di luar Git; validasi input; perlindungan sesi/CSRF sesuai metode autentikasi; rate limiting; upload file privat; least privilege.
- **Otorisasi:** pemeriksaan server-side pada setiap endpoint, pencarian, ekspor, dan akses dokumen; uji negatif terhadap IDOR/BOLA.
- **Auditabilitas:** aksi penting, status, persetujuan, perubahan peran, ekspor, dan tindakan Super Admin dapat ditelusuri.
- **Keandalan:** transaksi database, backup database dan file, uji restore, serta prosedur rollback terdokumentasi.
- **Kualitas:** unit, integration, API, authorization negative, dan end-to-end tests untuk alur kritis; scanner tidak boleh dimatikan demi build hijau.
- **Usability:** antarmuka berbahasa Indonesia yang konsisten, istilah tugas/status jelas, responsif untuk desktop dan perangkat mobile.
- **Aksesibilitas:** target WCAG 2.2 AA sebagai sasaran desain; jangan menyampaikan status hanya melalui warna.
- **Performa:** pagination untuk tabel besar, indeks untuk pencarian/filter penting, dan pemantauan query. Target angka performa disepakati setelah uji dengan volume data representatif.
- **Maintainability:** modular monolith; migrasi database berversi; lint, type checking, dan test otomatis di CI.
- **Deployment:** lingkungan local/test/staging terpisah dari production. Jangan menjalankan restore atau migrasi destruktif pada data produksi untuk pengujian.

## 12. Dashboard dan analitik

### Sekretariat

- Total tugas dan jumlah tiap status.
- Tugas belum diperbarui, terlambat, terkendala, dan menunggu pemeriksaan.
- Progres berdasarkan Rektor/Warek/unit/PIC jika data dan rumus tersedia.
- Jumlah Rapim per rentang waktu.
- Distribusi draf/final Decision Brief dan notulen.

### Rektor

- Seluruh Rapim, notulensi, Decision Brief, serta pemantauan tindak lanjut dalam mode baca saja.

### Warek

- Daftar rapat dan notulensi untuk dikelola; Decision Brief dan tindak lanjut untuk dibaca/dipantau.
- Tidak ada aksi membuat tindak lanjut.

### PIC

- Tugas sendiri, status resmi, tenggat, instruksi, progres yang dikirim, catatan, dan bukti yang diizinkan.
- Pengingat dashboard untuk tugas yang lewat tenggat atau memiliki tenggat dalam tujuh hari.
- Tidak ada ringkasan atau tautan ke notulen lengkap yang terbatas.

## 13. Risiko dan mitigasi

| Risiko | Mitigasi |
|---|---|
| PIC memperoleh notulen lewat endpoint lain | Negative authorization tests untuk URL/API/search/export/file; object-level authorization. |
| Status tugas berubah tanpa verifikasi | Validasi backend, transaksi, status history, audit log, dan constraint/trigger yang sesuai. |
| Perubahan live menimpa revisi notulensi | Kontrol versi, otorisasi edit server-side, dan penanganan conflict. |
| OCR atau AI salah mengidentifikasi putusan/PIC | Draf saja, konfirmasi manusia, simpan sumber/riwayat. |
| Dokumen final tertimpa | Versioning, checksum, pembatasan revisi, audit perubahan. |
| Backup ada tetapi tidak dapat dipulihkan | Uji restore berkala ke lingkungan terisolasi. |
| Perhitungan progres dipahami keliru | Tentukan rumus dan label statistik; uji terhadap data contoh. |
| Lingkup membengkak | Bangun MVP berdasarkan P0; fitur P1/P2 setelah alur inti lulus. |

## 14. Definisi MVP selesai

MVP bisa dipertimbangkan selesai bila alur berikut berhasil diuji pada lingkungan non-production:

1. Pengguna berwenang login dan mendapat akses sesuai peran.
2. Rapat dengan nomor, agenda bernomor otomatis, pembahasan, dan putusan dapat dibuat.
3. Sesi LIVE mengizinkan pengguna aktif Sekretariat, Manager Legal, Rektor, dan Warek mengedit notulen dengan kontrol revisi; PIC dan Super Admin tetap ditolak.
4. Putusan dapat ditandai sebagai action item atau bukan; satu putusan dapat menghasilkan beberapa tugas.
5. Tugas memiliki PIC utama/pendukung, output, target, dan riwayat progres.
6. PIC tidak dapat membaca notulen lengkap atau mengubah status resmi, termasuk lewat request API langsung.
7. Sekretariat dapat meninjau bukti dan mengubah status resmi dengan jejak audit.
8. Test, lint, type check, build dan security scans yang disyaratkan lulus atau memiliki pengecualian yang terdokumentasi.
9. Backup dan restore database serta file telah diuji di lingkungan terpisah.
10. Template ekspor notulen/Decision Brief telah divalidasi terhadap format resmi yang disetujui.

## 15. Asumsi dan keputusan terbuka

- Daftar PIC dan struktur organisasi lengkap belum tersedia; sistem harus mendukung konfigurasi unit dan garis pelaporan. Untuk demo/test terisolasi saja, PIC A/B/C sintetis dan unit sementara boleh dipakai; data ini bukan roster organisasi atau konfigurasi production.
- Nomor agenda dihasilkan otomatis; nomor rapat dapat diubah kapan saja oleh Sekretariat, Manager Legal, dan Warek. Blok pengesahan notulen tetap menunggu template resmi.
- Identitas notulis opsional disimpan per rapat untuk atribusi. Identitas tersebut tidak membatasi siapa yang boleh menyunting notulensi saat LIVE.
- Decision Brief wajib mencakup setiap putusan dari revisi sumbernya. Status rapat tetap dikelola Sekretariat; panel siklus rapat tidak ditampilkan.
- Integrasi AI/ChatGPT belum diputuskan. SITARA belum mengirim konten rapat ke layanan eksternal; persetujuan institusi, autentikasi, dan kebijakan data harus ditetapkan sebelum integrasi dibuat.
- Perlu ditetapkan apakah distribusi H+1 adalah target internal wajib atau target operasional.
- Rumus progres dashboard dan kebijakan tenggat/pengingat perlu disepakati.
- Retensi dokumen, retensi audit log, klasifikasi dokumen, dan kebijakan backup harus disetujui institusi.
- Pilihan OCR lokal versus layanan eksternal memerlukan evaluasi privasi dan kualitas terhadap contoh dokumen nyata yang telah diizinkan.
- Detail teknologi pemrosesan PDF dapat ditetapkan setelah prototipe cocok dengan format dokumen resmi.

## 16. Keterkaitan dokumen

- Visual dan komponen: [`system_design.md`](./system_design.md)
- Teknologi dan arsitektur: [`architecture.md`](./architecture.md)
- Aturan kerja AI/coding agent: [`agents.md`](./agents.md)
- Strategi test: [`TEST_STRATEGY.md`](./TEST_STRATEGY.md)
- Definition of Done: [`DEFINITION_OF_DONE.md`](./DEFINITION_OF_DONE.md)
- Draft skema database: [`sitara_schema_v1_draft.sql`](./sitara_schema_v1_draft.sql)
