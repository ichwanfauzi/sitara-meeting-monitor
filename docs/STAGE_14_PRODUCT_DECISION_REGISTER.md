# Stage 14 — Product Decision Register & Workflow Finalization

**Updated:** 12 November 2026 — supplemental owner decisions incorporated.

## 1. Tujuan dan ruang lingkup

Dokumen ini mencatat keputusan produk PD-01 sampai PD-04 dan membandingkannya
dengan implementasi SITARA yang diperiksa pada branch
`integration/sitara-main-sync`, HEAD
`42e4d9373779581a985ffc9808653ec5c49919c5`.

Audit bersifat statis dan read-only terhadap implementasi. Tidak ada API yang
dipanggil, database/runtime yang diakses, atau test yang dijalankan pada tahap
ini. Istilah **Implemented**, **Partially Implemented**, dan **Not Implemented**
menilai source/configuration yang ditemukan, bukan keberhasilan penggunaan
aplikasi live. Integrasi runtime tetap **Needs Verification**.

Stage 14 awal hanya membuat laporan. Pembaruan ini memasukkan keputusan produk
tambahan pemilik proses; tidak mengubah source, konfigurasi, database,
migration, API contract, atau dependency.

## 2. Ringkasan status keputusan

| Keputusan | Status implementasi | Ringkasan |
|---|---|---|
| PD-01 — Disposisi dan tindak lanjut oleh Rektor, Warek, Sekretariat | **Partially Implemented** | Ketiga role membuat Action Item dan memilih PIC aktif lintas unit dalam scope rapat. Migration `0018_action_item_unit_provenance` dan API menyimpan unit asal per assignment serta unit penanggung jawab per task; legacy rows tetap nullable tanpa backfill. Migration `0019_assignment_audit` mencatat assignment, penggantian PIC utama, dan pengakhiran PIC pendukung secara redacted dan atomik. Endpoint update detail masih tersisa; kewenangan untuk mengubah prioritas/tenggat belum diputuskan. |
| PD-02 — Approval Decision Brief oleh single approver | **Partially Implemented** | Workflow version-bound, submit/withdraw/approve/reject, audit atomik, dan UI telah ditambahkan pada Stage 18. Regresi SQLite/backend serta frontend lulus. Stage 19 memverifikasi PostgreSQL 16 concurrency/integrity pada target disposable; browser E2E belum diverifikasi. |
| PD-03 — Edit metadata rapat selama DRAFT/LIVE | **Not Implemented** | Keputusan final mengizinkan Sekretariat/Rektor/Warek mengubah metadata inti, agenda, dan peserta pada DRAFT/LIVE; handover notetaker LIVE perlu persetujuan satu pejabat yang berwenang. Source belum memiliki update metadata dan mutasi agenda/peserta hanya DRAFT. |
| PD-04 — Audit log penting lintas modul | **Partially Implemented** | Keputusan final menetapkan akses Secretariat berwenang, akses leader sesuai scope bisnis, grant tambahan eksplisit, audit atas read/export, retensi minimum 5 tahun atau kebijakan resmi yang lebih lama, append-only, dan rollback mutasi bisnis saat audit gagal. Source hanya memiliki domain history. |

## 3. Sumber dan hierarki keputusan

Dokumen yang diperiksa:

- [`docs/PRD.md`](./PRD.md)
- [`PROJECT_CONTEXT.md`](../PROJECT_CONTEXT.md)
- [`docs/architecture.md`](./architecture.md)
- [`docs/system_design.md`](./system_design.md)
- [`docs/ARCHITECTURE_DECISIONS.md`](./ARCHITECTURE_DECISIONS.md)
- [`docs/DEFINITION_OF_DONE.md`](./DEFINITION_OF_DONE.md)
- [`docs/TEST_STRATEGY.md`](./TEST_STRATEGY.md)
- README, model, schema, migration, service, router, frontend, dan tes terkait.

Keputusan PD-01 sampai PD-04 Stage 13 dan keputusan tambahan pemilik proses
tertanggal 12 November 2026 adalah kebijakan produk terbaru. Ketentuan yang
belum ada di source tetap dianggap belum diimplementasikan. Konflik dengan
PRD/ADR atau source dicatat; dokumen inti dan kode tidak diubah di sini.

## 4. PD-01 — Kewenangan disposisi dan tindak lanjut

### Keputusan

Rektor, Warek, dan Sekretariat dapat memberikan disposisi kepada pengguna,
unit organisasi, atau role di seluruh institusi. Ketiganya dapat membuat
Action Item dan secara eksplisit menunjuk atau mengubah PIC lintas unit sesuai
kewenangannya. Sistem mencatat unit asal PIC dan unit penanggung jawab
pekerjaan. PIC hanya memperoleh akses terhadap task dan dokumen yang diberikan
kepadanya. Kewenangan membuat/menugaskan task tidak mencakup perubahan status
resmi atau verifikasi penyelesaian, yang tetap menjadi kewenangan Sekretariat.

### Implementasi aktual

- `can_manage_meeting()` di
  [`backend/app/services/meetings.py`](../backend/app/services/meetings.py#L110)
  memberi Sekretariat kewenangan mengelola rapat, sementara Rektor/Warek
  terbatas pada rapat yang dibuat sendiri. Ini adalah kewenangan manajemen
  meeting, bukan endpoint disposisi.
- `create_action_item()` dan `create_assignment()` di
  [`backend/app/services/action_items.py`](../backend/app/services/action_items.py)
  menerima Sekretariat operasional dan Rektor/Warek yang berwenang dalam scope
  rapat. Target assignment harus berupa PIC aktif dengan keanggotaan unit aktif.
- `can_assign_pic()` di
  [`backend/app/services/organization.py`](../backend/app/services/organization.py)
  mengecek role aktif dan kelayakan target. Assignment Rektor/Warek dapat
  lintas unit; `can_manage_action_items()` membatasi operasinya ke rapat yang
  dapat mereka kelola.
- Rektor/Warek tetap membaca Action Item dan mengirim progres/bukti hanya dalam
  reporting scope yang aktif. Mereka tidak dapat mengubah status resmi.
  Aturan cakupan ada di
  [`backend/app/services/organization.py`](../backend/app/services/organization.py#L153)
  dan [`backend/app/services/action_items.py`](../backend/app/services/action_items.py#L516).
- API tersedia untuk membuat task dan assignment, tetapi tidak ada resource atau
  endpoint disposition terpisah pada saat analisis Stage 14. Pada pekerjaan
  Stage 16 saat ini, resource multi-target Disposition dan endpoint POST, GET,
  serta target directory sudah ditambahkan. Hak baca final: Sekretariat,
  Rektor, dan Warek aktif dengan akses ke rapat yang sama dapat membaca
  Disposisi; PIC, Super Admin, mixed-role yang memuat keduanya, dan pejabat di
  luar scope rapat ditolak:
  `POST /api/v1/action-items`,
  `POST /api/v1/action-items/{action_item_id}/assignments`,
  `POST /api/v1/action-items/{action_item_id}/assignments/{assignment_id}/end`.
  Route berada di
  [`backend/app/api/routes/action_items.py`](../backend/app/api/routes/action_items.py#L343).
- UI Action Item memberi Sekretariat, Rektor, dan Warek picker nama PIC dari
  direktori terotorisasi; backend tetap menerima ID pilihan dan memvalidasinya:
  [`frontend/src/ActionItemManagement.tsx`](../frontend/src/ActionItemManagement.tsx).
- Tes API dan organisasi memverifikasi assignment lintas unit bagi pimpinan,
  penolakan akses rapat di luar scope, dan pengecualian Super Admin:
  [`backend/tests/test_action_items.py`](../backend/tests/test_action_items.py),
  [`backend/tests/test_organization.py`](../backend/tests/test_organization.py).

### Perbedaan kewenangan yang teramati

| Role | Meeting/notulensi | Disposisi/Action Item | PIC/assignment | Status resmi |
|---|---|---|---|---|
| Sekretariat operasional | Akses operasional; dapat mengelola meeting | Dapat memberi disposition ke user/unit/role institusi dan membuat Action Item | Dapat menunjuk/mengubah PIC secara eksplisit lintas unit; catat unit asal dan unit penanggung jawab | Dapat mengubah dan memverifikasi, selain mixed-role Super Admin |
| Rektor | Meeting/notulensi sesuai kewenangan | Dapat memberi disposition ke user/unit/role institusi dan membuat Action Item | Dapat menunjuk/mengubah PIC secara eksplisit lintas unit sesuai kewenangan | Tidak dapat mengubah |
| Warek | Meeting/notulensi sesuai kewenangan | Dapat memberi disposition ke user/unit/role institusi dan membuat Action Item | Dapat menunjuk/mengubah PIC secara eksplisit lintas unit sesuai kewenangan | Tidak dapat mengubah |
| PIC | Tugas dan dokumen yang secara eksplisit diberikan; tidak menerima minutes penuh | Tidak dapat membuat disposition atau Action Item | Tidak menunjuk PIC | Tidak dapat mengubah |
| Super Admin | Ditolak dari akses bisnis yang dibatasi | Ditolak | Ditolak | Ditolak |

### Dampak dan rekomendasi

- **Frontend:** sediakan target user/unit/role dan directory PIC terotorisasi.
  Jangan meminta ID mentah. Tampilkan unit asal PIC, unit penanggung jawab,
  serta batas akses task/dokumen.
- **Backend/RBAC:** ketiga role dapat membuat disposition, Action Item, dan
  menunjuk PIC lintas unit bila actor memiliki kewenangan serta menunjuk
  secara eksplisit. Backend mencatat unit asal dan unit penanggung jawab serta
  membatasi PIC ke objek yang ditugaskan. Tetap kecualikan Super Admin dari
  izin bisnis meskipun mixed-role.
- **Database/API:** model `Disposition`, `DispositionTarget` dan
  `POST /api/v1/meetings/{meeting_id}/dispositions`,
  `GET /api/v1/meetings/{meeting_id}/dispositions`, dan
  `GET /api/v1/meetings/{meeting_id}/disposition-targets` kini tersedia.
  Directory dan pembacaan Disposisi hanya tersedia bagi pejabat aktif yang
  berwenang pada rapat tersebut; respons directory tidak memuat email atau
  kredensial. Satu Disposition dapat memiliki beberapa target bertipe user,
  unit, dan/atau role. Action Item dapat ditautkan melalui `disposition_id`
  opsional pada `POST /api/v1/action-items`, dengan exact source decision dan
  revision yang sama. Satu Disposition tetap dapat menghasilkan 0..N Action
  Items. Migration `0018_action_item_unit_provenance` kini mencatat unit asal
  per assignment dan unit penanggung jawab per task; assignment audit serta
  perubahan prioritas/tenggat masih perlu diselesaikan.
- **Auditability/testing:** setiap pembuatan disposisi/task, penentuan PIC,
  perubahan tenggat/prioritas, serta percobaan lintas cakupan perlu diuji dan
  dicatat.

### Acceptance criteria

1. Rektor, Warek, dan Sekretariat operasional dapat memberi disposition
   kepada target user, unit, atau role di seluruh institusi; PIC dan
   Super Admin ditolak, termasuk mixed-role Super Admin.
2. Record disposisi terhubung ke meeting dan keputusan/revisi sumber yang tepat.
3. Ketiga role dapat membuat Action Item dan menunjuk/mengubah PIC secara
   eksplisit lintas unit sesuai authority; sistem menyimpan unit asal PIC dan
   unit penanggung jawab.
4. Satu disposisi/keputusan dapat menghasilkan nol atau beberapa Action Item,
   masing-masing dengan PIC utama, PIC pendukung bila diizinkan, prioritas, dan
   tenggat yang dapat ditelusuri.
5. PIC hanya dapat membuka task dan dokumen yang ditugaskan kepadanya. Hak
   create/assign tidak memberi hak status resmi atau verifikasi penyelesaian.
6. Sekretariat operasional saja mengubah status resmi/verifikasi; semua
   percobaan lintas cakupan diuji di API, termasuk Super Admin mixed-role.

## 5. PD-02 — Persetujuan Decision Brief oleh single approver

### Keputusan

Satu pengguna berwenang yang memegang salah satu role Rektor, Warek, atau
Sekretariat dapat menyetujui versi Decision Brief tertentu; satu orang cukup
dan pembuat versi tidak boleh menyetujui versinya sendiri. Pengajuan dapat
dilakukan oleh pembuat versi atau pejabat approver berwenang (Rektor, Warek,
atau Sekretariat) dalam scope rapat. Pengajuan hanya diizinkan ketika status
rapat `FINAL` dan review minutes untuk revisi sumber versi itu `VALID`. Versi
yang menunggu dapat ditarik oleh pembuatnya dan diajukan ulang tanpa mengubah
isi versi. Penolakan wajib memiliki alasan; perbaikan isi harus disimpan
sebagai versi baru. Sistem mencatat actor, role, waktu, hasil, dan ID versi.

### Status implementasi Stage 18

- Migration `0017_decision_brief_approval` menambahkan event append-only yang
  terikat ke versi dan source revision. Status diturunkan dari event; konten
  versi tidak dimutasi. Audit event menggunakan allowlist dan transaksi yang
  sama dengan event workflow.
- API menyediakan submit, approve, reject, withdraw, dan histori. Submit
  menerima pembuat atau pejabat ber-role Rektor/Warek/Sekretariat yang
  berwenang dalam scope; withdrawal tetap hanya oleh pembuat saat pending.
- Service memeriksa FINAL+VALID untuk revisi sumber, mencegah self-approval
  author, mewajibkan alasan penolakan, dan mengunci meeting untuk serialisasi.
- Frontend menampilkan status/histori dan mengizinkan submit bagi role yang
  berwenang, termasuk pengguna selain pembuat.
- Regresi backend SQLite lulus 247 tes dengan coverage 84,17%; seluruh 105 tes
  frontend lulus.

**Pembaruan Stage 19:** suite PostgreSQL 16 concurrency/integrity pada target
disposable lulus 18 tes, termasuk perlindungan `TRUNCATE`. Browser E2E belum
dijalankan; persetujuan PostgreSQL tersebut tidak berarti database
development/production digunakan.

### Lifecycle keputusan

`DRAFT → PENDING_APPROVAL → APPROVED | REJECTED`

`PENDING_APPROVAL → WITHDRAWN → PENDING_APPROVAL` diperbolehkan untuk versi
immutable yang sama. Penarikan hanya saat pending dan dilakukan oleh pembuat
versi. Bila isi perlu diperbaiki setelah ditolak, buat versi baru; versi lama
beserta event submit/withdraw/reject tetap menjadi histori.

- `DRAFT`: konten versi belum diajukan.
- `PENDING_APPROVAL`: versi immutable menunggu satu approver yang memiliki
  role dan scope.
- `APPROVED`: satu approver menyetujui versi tepat tersebut; tidak menunggu
  role lain.
- `REJECTED`: approver menolak dengan alasan wajib; koreksi harus dibuat
  sebagai versi baru.
- `WITHDRAWN`: pembuat menarik pengajuan saat masih pending. Isi versi tidak
  berubah dan versi yang sama dapat diajukan kembali; seluruh event dipertahankan.

Source version hanya eligible bila meeting berstatus `FINAL` dan minutes
revision sumber mempunyai review `VALID` yang berlaku untuk revisi tersebut
(sesuai invariant finalisasi meeting). Revisi/sumber baru tidak mengubah
approval historis; versi brief tidak pernah berubah.

### Dampak dan rekomendasi

- **Frontend:** tampilkan status draf/menunggu/approved/rejected, tombol submit
  dan approval hanya untuk role yang berhak, identitas approver/waktu, serta
  versi sumber. Lindungi draft dari submit ganda dan tangani konflik versi.
- **Backend/RBAC:** buat policy yang menggabungkan role, status brief, akses
  meeting, dan scope. Tolak self-approval dengan membandingkan actor terhadap
  `created_by_id` versi.
- **Database/API:** approval harus terikat pada ID versi immutable. Record perlu
  identitas approver, role snapshot, hasil, timestamp, optional note, dan
  constraint yang mencegah terminal approval ganda. Tambahkan submit, approve,
  reject (alasan wajib), withdraw (hanya pending, oleh pembuat), dan histori
  event per versi.
- **Auditability/testing:** simpan event approval dan state versi secara
  konsisten; uji concurrency dua approver, status terminal, stale version,
  role campuran, dan audit trail.

### Acceptance criteria

1. Versi hanya dapat diajukan ketika meeting FINAL dan review minutes VALID
   untuk revisi sumber versi; konten versi immutable.
2. Salah satu approver berwenang dapat menyetujui sendiri; sistem tidak
   menunggu approval seluruh role, tetapi pembuat versi tidak dapat menyetujui
   versinya sendiri.
3. Approval mencatat user ID, role saat bertindak, waktu, hasil, dan ID versi.
4. Reject tanpa alasan ditolak; isi versi yang ditolak tidak dapat diedit dan
   koreksi dibuat sebagai versi baru.
5. Hanya pembuat dapat menarik versi saat pending; versi yang ditarik dapat
   diajukan ulang tanpa perubahan isi dan seluruh event tercatat.
6. Versi baru tidak mengubah atau mewarisi status/approval versi sebelumnya.
7. API menolak PIC, Super Admin, user tidak aktif, author self-approval,
   objek di luar scope, meeting non-FINAL, review tidak VALID, dan event
   duplikat/race dengan hasil deterministik.
8. Test membuktikan single approval, penolakan wajib beralasan, withdraw/
   resubmit, dan integritas histori versi.

## 6. PD-03 — Edit metadata rapat sebelum FINAL

### Keputusan

Metadata inti rapat, agenda, dan peserta boleh diedit dalam status DRAFT dan
LIVE oleh Sekretariat/Rektor/Warek sesuai scope. PIC tidak boleh mengubahnya.
Perubahan langsung ditolak pada FINAL/ARCHIVED. Pergantian notetaker saat LIVE
wajib melalui handover resmi yang disetujui salah satu pejabat Sekretariat,
Rektor, atau Warek dan dicatat dalam audit.

### Implementasi aktual

- `MeetingCreate` mendefinisikan nomor, judul, jenis, tanggal, waktu, lokasi,
  ketua, dan notetaker. Model `Meeting` menyimpan field tersebut dan status:
  [`backend/app/schemas/meetings.py`](../backend/app/schemas/meetings.py#L13),
  [`backend/app/models/meeting.py`](../backend/app/models/meeting.py#L67).
- Meetings router menyediakan GET/POST untuk list/detail/create, transisi,
  agenda, peserta, minutes, review, dan Decision Brief. Tidak ditemukan
  PUT/PATCH untuk mengubah metadata meeting:
  [`backend/app/api/routes/meetings.py`](../backend/app/api/routes/meetings.py#L250).
- `_require_editable_draft()` mensyaratkan status DRAFT; route agenda dan
  peserta memanggil helper ini. Tidak dapat menambah agenda/peserta saat LIVE
  melalui endpoint tersebut. Tidak ada endpoint handover:
  [`backend/app/api/routes/meetings.py`](../backend/app/api/routes/meetings.py#L226),
  [`backend/app/api/routes/meetings.py`](../backend/app/api/routes/meetings.py#L291).
- Frontend MeetingManagement menyediakan create form dan detail/lifecycle;
  tidak ditemukan update API/client method untuk meeting metadata:
  [`frontend/src/MeetingManagement.tsx`](../frontend/src/MeetingManagement.tsx#L230),
  [`frontend/src/api.ts`](../frontend/src/api.ts#L475).
- `test_meeting_metadata_mutations_require_csrf_and_do_not_write` menguji
  mutasi POST tanpa CSRF, bukan update metadata:
  [`backend/tests/test_meetings.py`](../backend/tests/test_meetings.py#L179).
  Belum ada bukti tes untuk izin update DRAFT/LIVE dan penolakan FINAL/ARCHIVED.

### Dampak dan rekomendasi

- **Frontend:** izinkan Sekretariat/Rektor/Warek yang berwenang mengubah
  metadata inti, agenda, peserta pada DRAFT/LIVE; PIC read-only. Sediakan
  permintaan/approval handover yang menunjukkan notetaker lama dan baru.
- **Backend/RBAC:** actor harus aktif, memiliki satu role yang diizinkan, dan
  dapat mengakses meeting. Handover LIVE harus dicatat sebagai tindakan
  tersendiri, disetujui salah satu dari Sekretariat/Rektor/Warek yang berwenang,
  lalu atomik mengganti notetaker dan menulis audit event.
- **Backend/RBAC:** tambah endpoint update dengan pemeriksaan autentikasi,
  CSRF, object-level access, serta status gate DRAFT/LIVE. Jangan mengubah
  meeting lifecycle atau membuat transisi FINAL/ARCHIVED dapat dibalik.
- **Database/API:** gunakan schema update yang membatasi field; pertahankan
  validasi waktu, pengguna aktif, nomor rapat unik, dan referensi. Putuskan
  apakah `meeting_number`, creator, start/finalization fields dapat diedit.
- **Auditability/testing:** simpan perubahan metadata dengan actor, nilai
  sebelum/sesudah yang aman, dan timestamp; uji update bersamaan dan perlombaan
  update dengan finalisasi.
- **Koreksi pasca finalisasi:** belum ada keputusan. Rekomendasi untuk
  dipertimbangkan: tidak mengubah snapshot final; buat amendment/correction
  append-only yang merujuk meeting/field/versi asal, dengan otorisasi dan audit
  tersendiri. Ini bukan izin untuk melakukan koreksi pada data FINAL/ARCHIVED.

### Acceptance criteria

1. Role dan cakupan meeting yang berhak dapat mengubah hanya field metadata
   yang telah ditetapkan pada DRAFT dan LIVE.
2. Update ditolak pada FINAL/ARCHIVED dengan response yang konsisten; data,
   lifecycle event, dan minutes snapshot tidak berubah.
3. Agenda/peserta dapat dikelola Sekretariat/Rektor/Warek yang berwenang pada
   DRAFT/LIVE; PIC ditolak pada API.
4. Nomor rapat tetap unik; field waktu, referensi user aktif, dan otorisasi
   objek divalidasi server-side.
5. Handover LIVE hanya efektif setelah persetujuan satu pejabat berwenang;
   pemohon yang sama tidak memperoleh hak notetaker sebelum approval.
6. Update metadata, agenda, peserta, dan handover serta audit event tercatat
   atomik. Tes mencakup CSRF, role/scope, tiap status, stale update, dan race
   dengan finalisasi/handover.

## 7. PD-04 — Audit log lintas modul

### Keputusan

SITARA wajib mencatat aktivitas penting pada meeting, agenda/peserta, minutes,
keputusan, Decision Brief, disposisi, Action Item/assignment, progres, evidence,
approval, serta administrasi/hak akses. Event sekurang-kurangnya memerlukan
actor, role saat aktivitas terjadi, tipe aksi, objek, waktu, hasil, dan before/
after yang relevan; correlation/reference ID dipakai bila tersedia.
Pencatatan audit adalah bagian wajib transaksi: jika audit event mutasi bisnis
gagal disimpan, mutasi utama harus rollback. Event append-only; pengguna biasa
tidak dapat mengubah atau menghapusnya.

Hak baca yang diputuskan:

- Semua Sekretariat operasional dapat membaca semua audit log; role
  `SUPER_ADMIN` tetap tidak memperoleh akses bisnis hanya karena mixed-role.
- Rektor dan Warek hanya dapat membaca event objek dalam scope akses bisnis
  masing-masing.
- Grant audit tambahan bersifat eksplisit dan tercatat. Hanya pejabat pemilik
  grant yang ditunjuk secara resmi dapat memberi atau mencabutnya.
- Super Admin tidak otomatis memperoleh akses; PIC tidak memiliki akses audit
  umum.
- Pembacaan dan ekspor audit dicatat sebagai event audit. Retensi minimal lima
  tahun atau lebih lama bila kebijakan arsip resmi ITPLN mewajibkan. Tidak ada
  penghapusan otomatis yang tidak disetujui.

### Implementasi aktual

- `MeetingStatusEvent` mencatat meeting ID, actor ID, status asal/tujuan, dan
  waktu; ini histori lifecycle terbatas, bukan audit semua perubahan:
  [`backend/app/models/meeting.py`](../backend/app/models/meeting.py#L149).
- Minutes review mencatat reviewer, revisi, hasil, catatan, dan waktu.
  Minutes revision mencatat author/waktu. Decision Brief mencatat author/waktu
  dan source revision. Ini adalah histori domain; role snapshot, correlation ID,
  outcome semua request, serta centralized object/event envelope tidak tampak.
- Action Item memiliki `status_histories`, assignment history, progress
  updates, completion verifications, dan evidence scan events. Trigger/migration
  melindungi beberapa history dari update/delete, misalnya
  [`backend/migrations/versions/0009_action_items.py`](../backend/migrations/versions/0009_action_items.py#L411)
  dan [`backend/migrations/versions/0011_evidence_scan_quarantine.py`](../backend/migrations/versions/0011_evidence_scan_quarantine.py#L158).
- Tidak ditemukan model/table/route terpadu `audit_log`/`audit_events`.
  [`backend/app/main.py`](../backend/app/main.py#L27) mendaftarkan router auth,
  health, action items, dan meetings saja.
- `docs/architecture.md` menjelaskan `audit_logs` sebagai entitas konseptual,
  sementara implementasi model/router yang diperiksa tidak menemukannya.
  `docs/DEFINITION_OF_DONE.md` juga mensyaratkan audit event untuk tindakan
  penting.

### Dampak dan rekomendasi

- **Frontend:** menyediakan timeline/audit view hanya untuk role yang mendapat
  hak audit; scope harus difilter server-side dan tidak membocorkan keberadaan
  event/objek di luar scope.
- **Backend:** buat event contract dan helper/service audit yang dipanggil
  dalam transaksi perubahan untuk sukses. Mutasi bisnis rollback jika audit
  gagal. Penolakan akses tetap menghasilkan response penolakan; pencatatan
  event `DENIED` dilakukan melalui transaksi terpisah dan kegagalannya
  memicu operational alert.
- **Database:** tabel append-only terpisah dengan index untuk object/time/
  actor, event ID, event type, actor ID, role snapshot, object type/ID,
  timestamp, outcome, correlation ID, serta before/after yang telah
  disaring. Terapkan retensi minimal lima tahun atau kebijakan arsip ITPLN
  yang lebih lama. Tidak ada auto-pruning sebelum kebijakan dan proses disposal
  disetujui. Trigger tidak membatasi owner/superuser yang mengubahnya; pisahkan
  privilege runtime/migration dan lindungi backup.
- **RBAC/API:** Sekretariat operasional dapat membaca seluruh log; Rektor/Warek
  dibatasi ke scope objek bisnis. Grant tambahan diberikan/dicabut hanya oleh
  pejabat pemilik grant yang ditunjuk. Grant/revoke dan read/export diaudit;
  Super Admin tidak memiliki akses otomatis.
- **Testing:** uji kelengkapan event untuk jalur sukses, kegagalan transaksi,
  pembuatan/update/approval, perubahan role, akses ditolak, append-only,
  redaksi data sensitif, serta konsistensi transaksi event dengan perubahan
  domain.

### Acceptance criteria

1. Setiap aktivitas dalam cakupan PD-04 menghasilkan event dengan actor ID,
   role snapshot, tipe aksi, object type/ID, timestamp, dan outcome; before/
   after dan correlation ID disertakan bila relevan/tersedia.
2. Kegagalan audit pada mutasi bisnis me-rollback perubahan utama. Kegagalan
   mencatat penolakan akses tidak mengubah response penolakan dan menghasilkan
   operational alert; event penolakan tidak menyatakan aksi berhasil.
3. Event tidak mengandung password, cookie/session/CSRF token, secret, file
   evidence, atau isi minutes/Brief yang tidak dibutuhkan untuk audit.
4. Pengguna biasa dan aplikasi runtime tidak dapat mengubah/menghapus event;
   DDL/runtime role terpisah. Batas database owner/superuser didokumentasikan.
5. Semua Sekretariat operasional dapat membaca seluruh log; Rektor/Warek hanya
   event dalam scope; grant ekstra diberikan/dicabut hanya pejabat pemilik
   grant yang ditunjuk. Super Admin tidak otomatis berhak.
6. Pembacaan dan ekspor audit menghasilkan event audit sebelum data
   dikembalikan; pencatatan read event tidak menyebabkan rekursi tanpa batas.
7. Retensi minimum lima tahun atau kebijakan resmi ITPLN yang lebih lama;
   penghapusan otomatis memerlukan proses retensi yang disetujui.
8. Tes membuktikan audit berfungsi untuk empat keputusan PD ini serta operasi
   bisnis yang disebutkan pada cakupan minimum.

## 8. Dampak lintas lapisan

| Area | Dampak konsolidasi |
|---|---|
| Frontend | Disposisi ke user/unit/role; approval single-approver per versi; edit metadata/agenda/peserta DRAFT/LIVE; handover notetaker; tampilan audit berizin. |
| Backend | Authorization create/assign PIC lintas unit; approval/withdraw per versi; edit meeting live/handover; audit write/read/export dengan scope server-side dan rollback atomik. |
| Database | Kemungkinan tabel disposisi, approval-version, metadata/audit event baru. Semua perubahan harus additive/bermigrasi via Alembic dan menjaga histori append-only. |
| RBAC | Rektor/Warek/Sekretariat memberi disposisi dan membuat Action Item, serta menunjuk PIC lintas unit secara eksplisit; PIC hanya melihat task/dokumen yang diberikan. Sekretariat tetap satu-satunya pengubah status resmi. |
| API contract | Kemungkinan endpoint disposisi, create/assign task untuk leader, submit/approve/reject Brief, update meeting; contract belum ada dan tidak diubah pada tahap ini. |
| Auditability | Domain history dipertahankan; centralized audit event atomik/append-only. Pembaca, scope, grant, read/export, redaksi dan retensi ditegakkan. |
| Testing | Tambahkan role/scope negative API tests, status workflow, snapshot-specific approval, metadata status gates/races, event completeness/atomicity, dan PostgreSQL concurrency/migration tests. |

## 9. Keputusan final dan detail desain tersisa

Keputusan produk tambahan yang sebelumnya terbuka kini ditetapkan:

1. **PD-01:** Rektor, Warek, dan Sekretariat dapat memberi disposisi kepada
   pengguna, unit organisasi, atau role; ketiganya dapat membuat Action Item
   dan menetapkan/mengubah PIC lintas unit sesuai kewenangan. PIC boleh berasal
   dari unit mana pun bila ditunjuk pejabat berwenang. Sistem mencatat unit
   asal PIC dan unit penanggung jawab pekerjaan. Disposisi dan assignment
   diaudit. PIC hanya mengakses task/dokumen yang diberikan, bukan status resmi
   atau verifikasi.
2. **PD-02:** submit hanya jika meeting `FINAL` dan review minutes `VALID`.
   Pembuat versi tidak boleh menyetujui versinya sendiri. Penolakan wajib
   beralasan; koreksi dibuat sebagai versi baru. Pembuat dapat menarik versi
   hanya saat pending; versi immutable yang sama boleh diajukan kembali.
3. **PD-03:** Sekretariat/Rektor/Warek dapat mengubah metadata inti, agenda,
   dan peserta dalam DRAFT/LIVE; PIC tidak. FINAL/ARCHIVED tidak dapat diedit
   langsung. Handover notetaker LIVE diminta oleh notetaker saat ini atau
   Sekretariat dan disetujui satu Sekretariat/Rektor/Warek; perubahan efektif
   setelah approval.
4. **PD-04:** seluruh Sekretariat operasional dapat membaca semua log;
   Rektor/Warek hanya event pada objek dalam scope masing-masing. Grant
   tambahan eksplisit diberikan/dicabut oleh pejabat pemilik grant yang
   ditunjuk. Super Admin tidak otomatis berhak. Read/export diaudit. Retensi
   minimal lima tahun atau kebijakan arsip resmi ITPLN yang lebih lama.
   Pengguna biasa tidak dapat mengubah/menghapus event. Jika audit write untuk
   mutasi bisnis gagal, seluruh mutasi rollback. Jika pencatatan akses ditolak
   gagal, response penolakan dipertahankan dan operational alert diterbitkan.

Keputusan multi-target telah ditutup: satu record disposisi dapat memiliki
satu atau beberapa target bertipe user, unit, dan/atau role. Pilihan unit asal
PIC diselesaikan melalui pemilihan eksplisit membership aktif dan validasi
backend. Detail teknis yang tersisa mencakup:
representasi actor anonim/system; identitas dan lifecycle pejabat pemilik grant
audit; serta mekanisme archive/disposal yang tetap memenuhi retensi. Satu
kebijakan field-level juga belum dinyatakan eksplisit:
role mana yang dapat menetapkan/mengubah prioritas dan tenggat Action Item,
serta apakah pembuat task dapat mengubahnya setelah dibuat. Jangan asumsikan
hak tersebut hanya dari kewenangan membuat task atau menetapkan PIC. Kebijakan
koreksi setelah FINAL/ARCHIVED belum ditetapkan dan tidak boleh membuka edit
langsung.

Konflik yang teramati tetap perlu ditangani pada tahap implementasi: PRD
FR-003 mensyaratkan update metadata tetapi source belum memiliki endpoint;
PRD FR-012 dan DoD meminta audit, sementara source hanya menyediakan domain
history; kewenangan task dalam keputusan produk lebih luas daripada layanan
yang saat ini Secretariat-only. `PROJECT_CONTEXT.md` juga menyebut dashboard
sintetis, sedangkan frontend worktree yang diperiksa API-backed. Dokumen inti
tidak diubah pada tahap ini.

## 10. Urutan implementasi yang direkomendasikan

Urutan Stage 15–19 disepakati sebagai berikut:

1. **Stage 15 — Audit Foundation:** model/event contract append-only, writer
   transaksi, rollback, access policy dasar, redaction, serta kontrol dan tes
   integritas.
2. **Stage 16 — Disposition & Action Item Authority:** disposisi user/unit/role,
   Action Item dari keputusan tanpa ketik ulang, kewenangan tiga role, PIC
   lintas unit dengan provenance unit asal/penanggung jawab, dan guard status
   resmi.
3. **Stage 17 — Meeting Metadata & LIVE Editing:** metadata/agenda/peserta
   DRAFT/LIVE dan formal notetaker handover.
4. **Stage 18 — Decision Brief Approval:** eligibility FINAL+VALID,
   single-approver, self-approval prevention, rejection reason, withdrawal,
   resubmission, dan immutable version history.
5. **Stage 19 — Integration & Security Validation:** integrasi, RBAC,
   transaksi, concurrency, audit, PostgreSQL, dan alur bisnis menyeluruh.

Tidak ada implementasi yang diotorisasi oleh register ini. Tiap stage tetap
memerlukan instruksi implementasi dan persetujuan runtime/database terpisah
bila diperlukan.

## 11. Kondisi repository dan batas verifikasi

Pemeriksaan akhir: branch `integration/sitara-main-sync`, HEAD
`42e4d9373779581a985ffc9808653ec5c49919c5`; 30 modified tracked, 14
untracked, 0 staged, dan 0 deleted. Ketiga dokumen Stage 14 tercatat sebagai
untracked dalam worktree yang sudah memiliki perubahan pengguna. Pembaruan ini
tidak menyentuh source/configuration lain; seluruh perubahan worktree lain
dipertahankan.

Tidak ada secret yang dibaca/ditampilkan dan tidak ada test, runtime, database,
migration, Docker, worker, atau evidence yang dijalankan pada pembaruan
dokumentasi ini.

**Status: STAGE 14 POLICY REGISTER UPDATED — DOCUMENTATION ONLY — NO CODE/RUNTIME CHANGES.**


## 12. Implementasi lanjut Stage 16 (2026-11-16)

- Provenance unit ditambahkan secara additive. PIC asal dipilih eksplisit dari membership aktif; unit penanggung jawab dipilih terpisah.
- Migrasi `0018_action_item_unit_provenance` menjaga data lama tetap `NULL` dan menolak downgrade setelah provenance terisi. Migrasi belum dijalankan terhadap database.
- Validasi saat ini memakai tes SQLite/API dan frontend. PostgreSQL disposable serta browser E2E belum dijalankan untuk slice ini.

## 13. PD-01 assignment audit follow-up (2026-11-16)

- `action_item.assignment_changed` mencatat penambahan PIC pendukung, penggantian PIC utama, dan pengakhiran PIC pendukung dengan role, ID assignment/PIC, dan unit asal.
- Event audit ditulis dalam transaksi yang sama dengan perubahan assignment. Payload tidak menyertakan alasan bebas dari pengguna; kegagalan pencatatan membatalkan perubahan.
- Migration `0019_assignment_audit` memperluas constraint audit yang ada dan mempertahankan trigger append-only. Downgrade ditolak bila event assignment sudah tersimpan.
- Tes API/migrasi SQLite dijalankan. PostgreSQL disposable, browser E2E, dan migration runtime tidak dijalankan.

## 14. Akses Rapim dan notulensi LIVE (2026-11-18)

- Sekretariat, Rektor, dan Warek dapat membaca seluruh metadata Rapim, notulen lengkap, dan Decision Brief.
- Ketiganya dapat mengedit notulen selama rapat `LIVE`. Notulis dicatat per rapat, dapat berbeda antar-rapat, dan bukan gerbang edit eksklusif; revisi tetap memakai `base_revision_id` untuk menolak konflik.
- PIC dan Super Admin tetap tidak dapat membaca notulen lengkap/Decision Brief, termasuk pada akun campuran.
- Hak tulis metadata/agenda/peserta serta pembuatan Decision Brief tidak ikut melebar; cakupan pengelolaan rapat yang berlaku tetap digunakan.
- Rektor/Warek tetap memiliki hak Action Item sesuai scope yang berlaku. Sekretariat menjadi pemilik monitoring lintas Rapim dan tetap satu-satunya pengubah status resmi.
- Implementasi tidak memerlukan migrasi database; field notulis yang sudah ada tetap menjadi pencatatan notulis setiap rapat.
