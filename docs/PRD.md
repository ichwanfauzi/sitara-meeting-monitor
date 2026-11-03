# Product Requirements Document (PRD) — SITARA

**Produk:** SITARA — Sistem Informasi Tindak Lanjut Rapat dan Arahan
**Versi dokumen:** 1.0-draft  
**Tanggal:** 14 Oktober 2026  
**Status:** Draft untuk validasi pemilik proses  
**Pemilik proses utama:** Direktorat Kesekretariatan  
**Target pengguna:** Rektor, Wakil Rektor (Warek), Sekretariat, dan PIC; Super Admin teknis terpisah.

> Dokumen ini mengubah kebutuhan yang telah disampaikan menjadi kebutuhan produk yang dapat dirancang, dibangun, dan diuji. Ketentuan administrasi yang belum dikonfirmasi ditandai sebagai asumsi atau keputusan terbuka; jangan menganggapnya sebagai kebijakan institusi final.

## 1. Ringkasan produk

SITARA adalah aplikasi web internal untuk membantu Direktorat Kesekretariatan mengelola hasil Rapat Pimpinan (Rapim), mencatat pembahasan dan putusan, menghasilkan draf Decision Brief, mendistribusikan tindak lanjut, memantau progres, memverifikasi bukti penyelesaian, dan menyimpan dokumen final dalam repositori terstruktur.

SITARA menggunakan satu sumber data terstruktur. Informasi yang dimasukkan saat rapat digunakan kembali untuk notulen, Decision Brief, action item, notifikasi, laporan, dan arsip sehingga mengurangi pencatatan berulang.

## 2. Masalah yang ingin diselesaikan

1. Hasil rapat, keputusan, dan tugas berisiko dicatat berulang kali di dokumen yang berbeda.
2. Satu rapat menghasilkan banyak putusan, tetapi progres tindak lanjut tiap putusan atau tugas dapat berbeda dan sulit dipantau apabila hanya tersimpan sebagai tabel dokumen.
3. Distribusi keputusan dan disposisi kepada Warek serta PIC perlu mengikuti rantai tanggung jawab yang jelas.
4. Pihak yang berbeda membutuhkan tampilan dan akses berbeda. PIC tidak boleh membaca notulen atau Decision Brief lengkap yang terbatas.
5. Status tugas, pembaruan progres, bukti, dan verifikasi perlu dapat ditelusuri.
6. Dokumen agenda, bahan rapat, notulen, Decision Brief, dan bukti tindak lanjut membutuhkan repositori yang mudah dicari.
7. Pengelolaan manual menyulitkan rekap jumlah rapat, status tugas, keterlambatan, dan tingkat penyelesaian.
8. Notulen dan Decision Brief perlu diekspor mengikuti format administrasi resmi, bukan sekadar dicetak dari tampilan dashboard.

## 3. Tujuan produk

- Mencatat notulensi Rapim secara langsung selama rapat oleh satu notulis yang ditunjuk.
- Menjadikan notulen terstruktur sebagai sumber untuk Decision Brief, action item, monitoring, ekspor, dan arsip.
- Mendukung keputusan yang tidak membutuhkan tindak lanjut tanpa membuat tugas secara otomatis.
- Memberi setiap tugas PIC utama, PIC pendukung bila diperlukan, output yang diharapkan, tenggat, riwayat progres, dan bukti.
- Menegakkan aturan status resmi: hanya Sekretariat operasional yang boleh mengubah status tugas.
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
- Mengedit notulen selama sesi live sebagai notulis yang ditunjuk; pengguna berwenang lainnya mendapat akses baca selama sesi live.
- Mengelola putusan, action item, distribusi, catatan, arsip, dan draf Decision Brief.
- Memverifikasi pengajuan hasil dari PIC/pimpinan dan mengubah status resmi tugas.
- Melihat statistik lintas rapat dan tugas sesuai kewenangan.

### 5.3 Rektor

- Membaca notulen dan Decision Brief sesuai kewenangan.
- Dapat membuat/mengelola notulen sesuai kewenangan; saat sesi live, hanya notulis yang ditunjuk menjadi editor.
- Membuat atau mendistribusikan tugas kepada bawahan sesuai struktur organisasi.
- Melihat progres bawahan, mengirim catatan/notifikasi, serta meninjau bukti.
- Tidak mengubah status resmi tugas secara langsung.

### 5.4 Wakil Rektor (Warek)

- Membaca notulen dan Decision Brief sesuai kewenangan.
- Dapat membuat/mengelola notulen sesuai kewenangan; saat sesi live, hanya notulis yang ditunjuk menjadi editor.
- Menerima keputusan sesuai bidang, mendisposisikan tugas kepada PIC di bawah koordinasi, dan memantau progres.
- Mengirim catatan/notifikasi dan meninjau bukti.
- Tidak mengubah status resmi tugas secara langsung.

### 5.5 PIC

- Melihat tugas yang ditugaskan kepadanya, instruksi, output, target waktu, pembaruan terkait, dan dokumen yang diizinkan.
- Mengirim pembaruan progres, melaporkan kendala, serta mengunggah bukti.
- Tidak dapat melihat notulen lengkap atau Decision Brief terbatas.
- Tidak dapat mengubah status resmi tugas.

## 6. Proses bisnis utama

1. Pengguna berwenang membuat metadata Rapim, termasuk nomor notulen manual, tanggal, waktu, lokasi, pimpinan rapat, notulis, peserta, dan agenda.
2. Saat status rapat `LIVE`, hanya notulis yang ditunjuk dapat mengedit isi notulen. Pengguna lain yang berwenang dapat melihat perubahan yang tersimpan. Detail frekuensi autosave dan refresh akan ditetapkan pada desain teknis.
3. Notulis memasukkan agenda, pembahasan, putusan/arahan, PIC yang disarankan, output, dan target penyelesaian.
4. Untuk setiap putusan, pengguna memilih `apakah_menjadi_action_item` (`Ya`/`Tidak`). `Tidak` berarti putusan tetap disimpan sebagai bagian notulen tetapi tidak membuat tugas. `Ya` memungkinkan pembuatan satu atau lebih action item.
5. Tugas memperoleh PIC utama dan dapat mempunyai satu atau lebih PIC pendukung. Penugasan harus mengikuti kewenangan organisasi/atasan yang diizinkan.
6. SITARA menyusun draf Decision Brief dari data putusan dan tugas; pengguna berwenang memeriksa, memperbaiki, dan mengesahkan dokumen.
7. Keputusan/tugas didistribusikan kepada pimpinan dan kemudian didisposisikan kepada PIC yang relevan.
8. PIC dan pimpinan terkait dapat mengirim update progres, catatan, kendala, serta bukti. Update tidak otomatis mengubah status resmi.
9. Sekretariat memeriksa pengajuan penyelesaian. Jika bukti perlu diperbaiki, Sekretariat mencatat alasan dan status yang sesuai. Jika hasil diverifikasi, Sekretariat menetapkan status `SELESAI`.
10. Dokumen final, bukti dan catatan tindak lanjut masuk repositori dengan hak akses tetap berlaku.
11. Dashboard dan laporan menghitung data dari sumber terstruktur, bukan angka yang diketik terpisah.

## 7. Persyaratan fungsional

Prioritas: **P0** = wajib untuk MVP; **P1** = setelah alur inti berjalan; **P2** = peningkatan berikutnya.

| ID | Prioritas | Persyaratan | Kriteria penerimaan ringkas |
|---|---|---|---|
| FR-001 | P0 | Autentikasi | Pengguna aktif dapat login/logout; kredensial salah dan akun nonaktif ditolak. |
| FR-002 | P0 | RBAC dan pembatasan objek | API memeriksa peran dan kewenangan atas setiap objek; akses terlarang ditolak di server. |
| FR-003 | P0 | Manajemen rapat | Pengguna berwenang dapat membuat, memperbarui metadata, dan melihat rapat sesuai izin. |
| FR-004 | P0 | Nomor notulen manual | Nomor resmi diinput mengikuti administrasi; sistem mencegah duplikasi. |
| FR-005 | P0 | Agenda dan pembahasan | Satu rapat memiliki banyak agenda; setiap agenda dapat memiliki beberapa pembahasan dan putusan. |
| FR-006 | P0 | Live notulensi satu penulis | Hanya notulis yang ditunjuk dapat mengedit saat live; pengguna berwenang lain hanya membaca. |
| FR-007 | P0 | Putusan menjadi action item | Untuk setiap putusan tersedia pilihan Ya/Tidak; `Tidak` tidak membuat tugas. |
| FR-008 | P0 | Penugasan | Action item memiliki PIC utama, dapat memiliki beberapa PIC pendukung, output, dan tenggat. |
| FR-009 | P0 | Status resmi | Hanya Sekretariat yang mengubah status resmi; setiap transisi tercatat. |
| FR-010 | P0 | Pembaruan progres | PIC/pimpinan terkait dapat mengirim update dan kendala tanpa mengubah status resmi. |
| FR-011 | P0 | Bukti dan verifikasi | PIC dapat mengunggah bukti pada tugas sendiri; Sekretariat dapat meninjau dan meminta revisi. |
| FR-012 | P0 | Audit log | Perubahan sensitif mencatat pelaku, waktu, objek, tindakan, dan data perubahan yang aman disimpan. |
| FR-013 | P1 | Decision Brief | Draf dihasilkan dari data terstruktur dan harus ditinjau sebelum final. |
| FR-014 | P1 | Repositori | Dokumen agenda, bahan, notulen, Decision Brief, serta tindak lanjut dapat diarsipkan dan dicari sesuai akses. |
| FR-015 | P1 | Notifikasi | Penerima mendapatkan notifikasi relevan tentang tugas baru, tenggat, update, kendala, dan pengajuan persetujuan. |
| FR-016 | P1 | Ekspor PDF/tabel | Hasil ekspor memakai template yang disetujui dan menghormati izin akses. |
| FR-017 | P1 | Pencarian dan filter | Pencarian mendukung kata kunci, tanggal, nomor rapat, agenda, status, dan parameter lain sesuai peran. |
| FR-018 | P1 | Dashboard dan rekap | Statistik rapat/tugas dapat difilter dengan data yang sumbernya dapat ditelusuri. |
| FR-019 | P2 | OCR/digitasi | File PDF/gambar dapat diekstrak menjadi draf teks yang dapat diperiksa sebelum disimpan. |
| FR-020 | P2 | Bantuan AI | AI dapat membuat usulan ringkasan/Decision Brief; pengguna berwenang harus meninjau sebelum final. |

## 8. Aturan bisnis wajib

1. Peran resmi: `SUPER_ADMIN`, `SEKRETARIAT`, `REKTOR`, `WAREK`, dan `PIC`.
2. Super Admin dan Sekretariat adalah identitas peran yang berbeda.
3. Notulen penuh serta Decision Brief terbatas hanya dapat dibuka oleh pengguna pimpinan/Sekretariat yang berwenang. PIC tidak boleh mendapatkannya lewat URL langsung, API, ID yang dimanipulasi, pencarian, ekspor, atau URL penyimpanan.
4. Saat rapat berstatus live, hanya notulis yang ditunjuk menjadi editor. Hak edit harus diperiksa backend.
5. Status resmi tugas hanya boleh diubah oleh pengguna berperan Sekretariat yang berwenang. Pembatasan berlaku di API dan perlu didukung kontrol database yang sesuai.
6. Lima status resmi: `BELUM_DIMULAI`, `BERPROSES`, `TERKENDALA`, `MENUNGGU_ACC`, `SELESAI`.
7. `SELESAI` hanya boleh ditetapkan setelah hasil diverifikasi oleh Sekretariat dan record verifikasi disimpan.
8. Putusan yang tidak menjadi action item tetap tersimpan di notulen dan tidak membuat tugas.
9. Satu putusan boleh menghasilkan beberapa action item; setiap tugas dapat memiliki satu PIC utama aktif dan satu atau lebih PIC pendukung.
10. Delegasi harus berada dalam ruang lingkup kewenangan penugas dan garis organisasi yang diizinkan.
11. Nomor notulen diinput manual; finalisasi tidak boleh mengubah nomor diam-diam.
12. Dokumen bersifat privat secara default. `storage_key` tidak boleh dikirim ke klien yang tidak berwenang.
13. Finalisasi/revisi dokumen harus mempertahankan versi dan riwayat. Dokumen resmi tidak boleh diam-diam ditimpa.
14. Setiap pemeriksaan notulensi mengacu pada satu revisi tertentu. Revisi baru membuat pemeriksaan lama tidak berlaku untuk finalisasi; hanya pemeriksaan terbaru yang `VALID` pada revisi aktif yang dapat memenuhi syarat `LIVE → FINAL`.
14. Setiap ekspor dokumen terbatas harus melalui pemeriksaan akses dan dicatat pada audit log.
15. Tidak ada aksi AI yang boleh mengubah status tugas atau mengesahkan dokumen secara otomatis.

## 9. Model status tugas

- `BELUM_DIMULAI`: tugas ada, pelaksanaan belum mulai.
- `BERPROSES`: pelaksanaan sedang berlangsung.
- `TERKENDALA`: ada hambatan yang perlu ditangani atau dieskalasikan.
- `MENUNGGU_ACC`: hasil diajukan dan menunggu pemeriksaan Sekretariat.
- `SELESAI`: hasil diverifikasi dan status ditetapkan Sekretariat.

Update progres (termasuk persentase jika dipakai) terpisah dari status resmi. Definisi rumus progres dashboard harus dikunci sebelum dashboard statistik dibuat. Jangan menyamakan rata-rata persentase dengan proporsi jumlah tugas selesai tanpa label yang benar.

## 10. Dokumen, ekspor, digitasi, dan AI

- Notulen resmi harus mengikuti contoh format yang disediakan: identitas dokumen, nomor, tanggal, waktu/tempat, pimpinan/peserta, agenda, pokok bahasan, putusan/tindak lanjut, PIC, target, penutupan, serta blok pejabat/notulis yang berlaku.
- Template PDF final perlu diuji untuk tabel multi-halaman, header tabel berulang, nomor halaman, ukuran kertas, margin, dan pemisahan tanda tangan. Isi persis blok pengesahan mengikuti template resmi yang disetujui.
- Decision Brief merupakan ringkasan keputusan/tindak lanjut (misalnya keputusan/perintah, PIC, output, target). Notulen tetap menjadi rekam rapat lengkap.
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

### Rektor/Warek

- Tugas dalam lingkup tanggung jawab.
- Tugas PIC aktif, tertunda, terkendala, dan perlu ditinjau.
- Pembaruan terakhir serta tenggat.

### PIC

- Tugas sendiri, status resmi, tenggat, instruksi, progres yang dikirim, catatan, dan bukti yang diizinkan.
- Tidak ada ringkasan atau tautan ke notulen lengkap yang terbatas.

## 13. Risiko dan mitigasi

| Risiko | Mitigasi |
|---|---|
| PIC memperoleh notulen lewat endpoint lain | Negative authorization tests untuk URL/API/search/export/file; object-level authorization. |
| Status tugas berubah tanpa verifikasi | Validasi backend, transaksi, status history, audit log, dan constraint/trigger yang sesuai. |
| Perubahan live menimpa teks notulis | Satu writer, penanda versi/revision, kontrol edit server-side, dan penanganan conflict. |
| OCR atau AI salah mengidentifikasi putusan/PIC | Draf saja, konfirmasi manusia, simpan sumber/riwayat. |
| Dokumen final tertimpa | Versioning, checksum, pembatasan revisi, audit perubahan. |
| Backup ada tetapi tidak dapat dipulihkan | Uji restore berkala ke lingkungan terisolasi. |
| Perhitungan progres dipahami keliru | Tentukan rumus dan label statistik; uji terhadap data contoh. |
| Lingkup membengkak | Bangun MVP berdasarkan P0; fitur P1/P2 setelah alur inti lulus. |

## 14. Definisi MVP selesai

MVP bisa dipertimbangkan selesai bila alur berikut berhasil diuji pada lingkungan non-production:

1. Pengguna berwenang login dan mendapat akses sesuai peran.
2. Rapat dengan nomor manual, agenda, pembahasan, dan putusan dapat dibuat.
3. Sesi live menerapkan satu notulis sebagai editor.
4. Putusan dapat ditandai sebagai action item atau bukan; satu putusan dapat menghasilkan beberapa tugas.
5. Tugas memiliki PIC utama/pendukung, output, target, dan riwayat progres.
6. PIC tidak dapat membaca notulen lengkap atau mengubah status resmi, termasuk lewat request API langsung.
7. Sekretariat dapat meninjau bukti dan mengubah status resmi dengan jejak audit.
8. Test, lint, type check, build dan security scans yang disyaratkan lulus atau memiliki pengecualian yang terdokumentasi.
9. Backup dan restore database serta file telah diuji di lingkungan terpisah.
10. Template ekspor notulen/Decision Brief telah divalidasi terhadap format resmi yang disetujui.

## 15. Asumsi dan keputusan terbuka

- Daftar PIC dan struktur organisasi lengkap belum tersedia; sistem harus mendukung konfigurasi unit dan garis pelaporan.
- Pemilik proses perlu menetapkan aturan penomoran dan blok pengesahan notulen secara final; nomor akan diinput manual.
- Perlu dikonfirmasi apakah Decision Brief selalu diperlukan untuk setiap Rapim atau hanya rapat/putusan tertentu.
- Untuk workflow API rapat yang sudah diputuskan, hanya Sekretariat tanpa `SUPER_ADMIN` yang boleh memulai rapat (`DRAFT → LIVE`), memeriksa notulensi, memfinalisasi, dan mengarsipkan rapat (`FINAL → ARCHIVED`); pemeriksa boleh menjadi finalisator yang sama. Pembuatan metadata rapat tetap menghasilkan status `DRAFT`. Notulis yang ditunjuk menjadi satu-satunya penulis revisi saat rapat `LIVE`. Keputusan pemilik proses pada 21 Oktober 2026 menetapkan Sekretariat dan pimpinan yang berwenang dalam lingkup rapat dapat membuat draf Decision Brief. Kewenangan untuk meninjau, mengesahkan, dan memfinalisasi Decision Brief masih perlu ditetapkan.
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
