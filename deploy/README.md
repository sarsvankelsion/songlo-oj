# Dựng trên máy chủ Linux

Máy chủ trường là **Linux**. Tài liệu này chỉ nói về Linux vì phần chấm bài dựa
vào những thứ chỉ có trên POSIX — `resource.setrlimit`, `os.setsid`,
`os.wait4`, `setuid`. Trên Windows, `server/seed.py` và `server/worker.py` vẫn
chạy được để phát triển, nhưng chỉ có trần thời gian thực, không có giới hạn
CPU, và **không hạ được quyền**. Xem ghi chú đầu `server/sandbox.py`.

## 1. Chuẩn bị

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip g++ nginx

sudo useradd --system --create-home --shell /usr/sbin/nologin songlo
sudo mkdir -p /opt/songlo /var/lib/songlo
sudo chown songlo:songlo /opt/songlo /var/lib/songlo
```

Lấy mã nguồn về `/opt/songlo` (git clone hoặc copy), rồi:

```bash
sudo -u songlo python3 -m venv /opt/songlo/.venv
sudo -u songlo /opt/songlo/.venv/bin/pip install -r /opt/songlo/server/requirements.txt

# Thư mục ảnh đại diện. Ứng dụng tự tạo khi có người tải ảnh lên đầu tiên, nhưng
# tạo sẵn ở đây thì chắc chắn đúng chủ sở hữu — tự tạo lúc chạy thì nó thuộc về
# tài khoản mà tiến trình web đang dùng, và nếu tài khoản đó không phải `songlo`
# thì lần sao lưu hay chuyển máy sau này sẽ gặp một thư mục không đọc được.
sudo install -d -o songlo -g songlo -m 755 /var/lib/songlo/avatars

# Thư mục làm việc cho việc **sinh bộ dữ liệu từ lời giải mẫu**. Cố ý tách khỏi
# `judge/`: việc sinh dữ liệu chạy trong tiến trình web (tài khoản `songlo`),
# còn `judge/` thuộc `root` vì chỉ tiến trình chấm chạy bằng root mới ghi được
# vào đó. Dùng chung một thư mục thì mỗi lần giáo viên bấm "Sinh bộ dữ liệu" đều
# nhận lỗi 500, và lỗi đó không tái hiện được ở máy phát triển.
#
# Ứng dụng tự tạo thư mục này khi dùng lần đầu (tiến trình web sở hữu
# `/var/lib/songlo`), nhưng tạo sẵn thì chủ sở hữu chắc chắn đúng.
sudo install -d -o songlo -g songlo -m 700 /var/lib/songlo/gendata
```

Một điều phải biết về quyền của việc sinh dữ liệu: chương trình do giáo viên gửi
lên chạy bằng **tài khoản của tiến trình web** (`songlo`), không phải bằng tài
khoản hạ quyền `songlo-judge` như mã học sinh. Lý do: hạ quyền cần `root`, mà
tiến trình web chạy bằng `songlo`; `sandbox` nuốt lỗi hạ quyền một cách có chủ ý
để không làm mọi thứ đổ vỡ. Giới hạn thời gian, bộ nhớ và kích thước tệp vẫn áp
dụng đầy đủ — thiếu chỉ là tầng cách ly theo tài khoản.

Muốn bỏ khác biệt đó thì phải chuyển việc sinh dữ liệu sang `worker.py` và cho
nó thành một việc trong hàng đợi. Đó là việc lớn hơn; ghi ở đây để nếu trường mở
quyền soạn đề cho nhiều giáo viên hơn thì biết chỗ cần làm trước.

Cần **Pillow** trong `requirements.txt` cho phần ảnh đại diện. Thiếu nó thì mọi
thứ khác vẫn chạy, chỉ riêng việc tải ảnh lên là báo lỗi — xem `server/avatars.py`.

## 2. Tài khoản chạy bộ chấm — đọc kỹ mục này

Đây là bước quan trọng nhất và cũng là bước dễ bỏ qua nhất.

**Bộ chấm phải chạy dưới một tài khoản riêng, không phải tài khoản của web
server.** Lý do không phải là thẩm mỹ:

`RLIMIT_NPROC` — giới hạn số tiến trình chống "fork bomb" — đếm theo **mã người
dùng thực**, không theo tiến trình. Nếu worker chấm dùng chung tài khoản với
nginx hay với tiến trình web, giới hạn đó áp lên **tổng số tiến trình của tài
khoản**, và một buổi học có ba chục em nộp bài cùng lúc có thể làm worker chết
vì hết hạn mức tiến trình.

Tạo một tài khoản riêng cho bộ chấm, không có quyền gì:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin songlo-judge
id songlo-judge        # ghi lại uid và gid, sẽ dùng ở bước 4
```

Rồi cấu hình worker chạy bằng **root** nhưng hạ quyền tiến trình con xuống
`songlo-judge`. Cách này mạnh hơn việc cho worker chạy thẳng bằng
`songlo-judge`: worker cần quyền ghi vào CSDL, còn mã học sinh thì không nên có
quyền gì cả. `sandbox.py` hạ quyền trong tiến trình con, sau `fork` và trước
`exec`, nên mã học sinh chạy bằng `songlo-judge` còn worker vẫn ghi được CSDL.

## 3. Biến môi trường

Đặt trong `/etc/songlo.env`, quyền `600`, chủ sở hữu `root`:

```ini
SONGLO_VAR=/var/lib/songlo
SONGLO_SECRET=<chuỗi ngẫu nhiên, xem lệnh bên dưới>
SONGLO_COMPILER=g++
```

Sinh khoá bí mật:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Khoá này ký cookie phiên đăng nhập. **Phải cố định**: đổi nó thì mọi người bị
đăng xuất. Và phải khác giá trị mặc định trong mã nguồn — giá trị đó ai đọc mã
cũng biết, nên dùng nó là để bất kỳ ai tự ký được cookie đăng nhập của giáo viên.

`SONGLO_VAR` là gốc chung: cả `server/app.py` lẫn `server/worker.py` đều suy ra
đường dẫn CSDL và thư mục chấm từ nó, nên hai tiến trình không thể lệch nhau.

### 3.1. Nhờ AI viết bộ sinh dữ liệu (tuỳ chọn)

Không đặt gì thì tính năng ẩn hẳn — giáo viên không thấy thẻ đó. Muốn bật, thêm
ba dòng này vào `/etc/songlo.env`:

```ini
SONGLO_AI_BASE=https://sarsed.eu.cc/v1
SONGLO_AI_KEY=<khoá API>
SONGLO_AI_MODEL=jw/claude-opus-4-8
```

**Khoá phải nằm ở đây, không nằm trong mã nguồn.** Repo này là công khai; một khoá
viết thẳng vào `app.py` là một khoá đã bị lộ, và xoá nó ở commit sau không thu hồi
được — nó vẫn nằm trong lịch sử git. `.gitignore` đã chặn `.env`.

**Đổi mô hình thì phải thử trước, và thử bằng cách chạy thật.** Đã gặp: mô hình
đầu tiên (`oc/space-bunny-free`) trả về đúng ở lần đo này và **không trả lời trong
90 giây** ở lần đo sau — cùng một đề. Đo hai lần trên cùng một đề, dịch cả hai
chương trình, rồi **đối chiếu đáp án với một cài đặt độc lập** (viết bằng Python).
Một lời giải mẫu sai vẫn sinh ra đủ bộ dữ liệu trông như thật, nên "sinh được" và
"sinh đúng" là hai chuyện khác nhau. `_vps/_model_test.py` trong workspace làm
đúng việc này; nó dùng đề Kadane vì trường hợp dãy toàn số âm là chỗ hay sai nhất.

Bốn điều đã đo thật trên máy chủ, không phải phỏng đoán:

**`SONGLO_AI_BASE` phải là endpoint kiểu OpenAI** (`/v1/chat/completions`).
Đường dẫn đầy đủ được ghép bằng `base.rstrip("/") + "/chat/completions"`.

**Máy chủ AI đứng sau Cloudflare, và Cloudflare chặn User-Agent mặc định của thư
viện chuẩn.** Cùng một yêu cầu: không đặt `User-Agent` thì **403**, đặt bất kỳ giá
trị nào khác thì **200**. `aiwriter.py` đã đặt `SongLoOJ/1.0`; đổi sang một thư
viện HTTP khác thì phải đặt lại, nếu không sẽ hỏng đúng trên máy chủ thật và đọc
thì y như "sai khoá".

**Phải nâng thời hạn của gunicorn.** Một lần nhờ AI viết mất **16–35 giây** — đo
thật hai lần liên tiếp trên máy chủ này, cùng một đề, chỉ khác nhau ở mức tải của
máy chủ AI. Gunicorn mặc định cắt ở 30 giây, tức là nằm **giữa** khoảng đó: lần
đo 16 giây chạy êm, còn lần 34 giây — nếu không nâng — đã trả 502 sau khi giáo
viên chờ xong. Thêm `--timeout 120` vào `ExecStart`:

```ini
ExecStart=/opt/songlo/.venv/bin/gunicorn \
    --workers 2 --threads 4 --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile - --error-logfile - \
    "server.app:app"
```

`SONGLO_AI_TIMEOUT` (mặc định 90 giây) phải **nhỏ hơn** giá trị này, để lỗi hiện ra
thành một câu giải thích thay vì một trang 502.

**Hạn mức là của riêng từng mô hình, và máy chủ nói rõ còn bao lâu.** Gọi liên tiếp
cùng một đề bằng `jw/claude-opus-4-8`: 3 lần qua (12–13,6 giây), rồi **503** với
thân phản hồi `[403]: HTTP 403 (reset after 1m 29s)`. Chặn đủ khoảng **2 phút**.
Cùng lúc đó `oc/space-bunny-free` qua **10/10** yêu cầu liên tiếp — nên đây là hạn
mức của **riêng mô hình đó**, và thứ làm nó cạn là gọi dồn dập.

`aiwriter.py` đọc con số `reset after …` trong thân phản hồi (và tiêu đề chuẩn
`Retry-After`) rồi mới quyết định:

- chờ tại chỗ rồi thử lại nếu máy chủ nói ≤ `MAX_WAIT_SECONDS` (25 giây);
- quá 25 giây thì **không chờ**: báo thẳng "còn khoảng 2 phút nữa mới dùng lại
  được". Chờ đủ 90 giây thì giáo viên ngồi nhìn vòng xoay, mà ngân sách
  `MAX_TOTAL_SECONDS` (100 giây) của cả yêu cầu cũng hết theo.

Đo thật: thử lại mù quáng sau 1 giây và 3 giây **không cứu được lần nào** (5 lần
gọi, có thử lại, vẫn 3/5 như khi chưa có). Vì vậy con số của máy chủ được ưu tiên
hơn mọi giá trị đoán; `RETRY_DELAYS` chỉ còn **một** lần, dành cho trường hợp máy
chủ không nói gì (mạng chập chờn, kết nối bị đóng).

Cách dùng thực tế: vài phút một đề thì không gặp; bấm liên tiếp 5 đề thì gặp. Nếu
trường cần sinh dồn dập, cách rẻ nhất là thêm **mô hình thứ hai** làm phương án dự
phòng — nhưng phải là lựa chọn **hiện ra cho giáo viên thấy**, không phải tự động
đổi ngầm: mô hình cũ (`oc/space-bunny-free`) đã từng ra đề sai, nên im lặng quay
về nó còn tệ hơn là báo lỗi.

Đổi lại: một yêu cầu treo sẽ giữ một luồng lâu hơn trước. Với `--workers 2
--threads 4` và ba giáo viên thì không đáng lo; nếu trường mở cho nhiều giáo viên
hơn thì nên chuyển việc gọi AI sang `worker.py` thành một việc trong hàng đợi, chứ
đừng nâng thời hạn thêm nữa.
Chỉ cần đặt biến này, không cần đặt `SONGLO_DB` riêng.

## 4. systemd

`/etc/systemd/system/songlo-web.service`:

```ini
[Unit]
Description=Song Lo OJ - web
After=network.target

[Service]
User=songlo
Group=songlo
EnvironmentFile=/etc/songlo.env
WorkingDirectory=/opt/songlo
ExecStart=/opt/songlo/.venv/bin/gunicorn \
    --workers 2 --threads 4 --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile - --error-logfile - \
    "server.app:app"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/songlo-worker.service` — bản đầy đủ nằm trong repo tại
`deploy/songlo-worker.service`, chép thẳng vào `/etc/systemd/system/`:

```bash
sudo cp /opt/songlo/deploy/songlo-worker.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now songlo-worker
```

Hai chi tiết trong tệp đó đều là lỗi đã gặp thật, không phải trang trí:

**`EnvironmentFile=/etc/songlo.env` là bắt buộc.** Thiếu nó, `server/worker.py`
rơi về mặc định `server/var/songlo.db`, không thấy CSDL, và thoát với mã 2. Triệu
chứng cực khó đoán vì web vẫn trả 200 và đăng nhập vẫn được — chỉ có bài nộp là
mãi không ra kết quả. Nếu đã có sẵn `SONGLO_VAR` trong `/etc/songlo.env` thì chỉ
cần đúng một dòng này, không cần đặt `SONGLO_DB` riêng.

**`StartLimitIntervalSec` thuộc `[Unit]`, không thuộc `[Service]`.** Đặt sai phần,
systemd ghi `Unknown key name ... ignoring` rồi **bỏ qua im lặng**; giới hạn mặc
định (5 lần trong 10 giây) vẫn còn hiệu lực và nó sẽ thôi thử lại sau vài lần
crash — đúng lúc cần nhất.

Nếu dùng tài khoản chấm riêng (khuyến nghị, xem bước 2), thêm:

```ini
Environment=SONGLO_JUDGE_RUNAS_UID=<uid của songlo-judge>
Environment=SONGLO_JUDGE_RUNAS_GID=<gid của songlo-judge>
Environment=SONGLO_JUDGE_MAX_PROCS=64
```

```bash
sudo chmod 600 /etc/songlo.env
sudo systemctl daemon-reload
sudo systemctl enable --now songlo-web songlo-worker
sudo systemctl status songlo-web songlo-worker
```


## 5. Tạo dữ liệu lần đầu

```bash
sudo -u songlo env $(cat /etc/songlo.env | xargs) \
    /opt/songlo/.venv/bin/python -m server.seed
```

Lệnh này in ra danh sách tài khoản. **Đổi mật khẩu giáo viên ngay**, và đặt
mật khẩu riêng cho từng học sinh thay vì dùng chung một mật khẩu.

## 6. nginx

```nginx
server {
    listen 80;
    server_name songlo.example.edu.vn;

    client_max_body_size 256k;   # mã nguồn C++ không bao giờ cần hơn thế

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Tệp tĩnh do nginx trả, không qua Python.
    location /assets/ {
        alias /opt/songlo/demo/assets/;
        expires 7d;
        access_log off;
    }
}
```

Sau đó cài HTTPS. Trang đăng nhập gửi mật khẩu dạng thô qua mạng, nên **bắt buộc
phải có HTTPS** trước khi cho học sinh dùng thật:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d songlo.example.edu.vn
```

### Named tunnel — hostname cố định

Dùng khi **đã có tên miền trên Cloudflare** nhưng không muốn mở cổng 80/443 ra
ngoài (máy chủ sau NAT, hoặc không được phép mở cổng). Hostname **không đổi** giữa
các lần khởi động, khác hẳn `*.trycloudflare.com`.

Mỗi dịch vụ nên có **tunnel riêng**. `cert.pem` ở `/root/.cloudflared/` là chứng
thư cấp **tài khoản**, nên tạo được tunnel mới hoàn toàn bằng dòng lệnh — không
cần mở trình duyệt, không cần đụng vào tunnel đang chạy.

```bash
# 1. Tạo tunnel riêng. Lệnh ghi chứng thư vào /root/.cloudflared/<uuid>.json,
#    chuyển nó sang /etc/songlo/ cho tách bạch.
cloudflared tunnel create songlo-oj
mv /root/.cloudflared/<uuid>.json /etc/songlo/songlo-oj.json
chmod 600 /etc/songlo/songlo-oj.json

# 2. Cấu hình (xem deploy/cloudflared.yml — nhớ đổi uuid)
install -m 644 deploy/cloudflared.yml /etc/songlo/cloudflared.yml

# 3. Trỏ hostname. --config VÀ uuid đều phải có — xem cảnh báo bên dưới.
cloudflared tunnel --config /etc/songlo/cloudflared.yml \
    route dns --overwrite-dns <uuid> oj.sarsed.eu.cc

# 4. Chạy
install -m 644 deploy/songlo-tunnel.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now songlo-tunnel
```

#### ⚠️ `route dns` đọc cấu hình mặc định, và có thể gắn bản ghi vào SAI tunnel

Đây là bẫy đã xảy ra thật khi dựng hostname này. Lệnh

```bash
cloudflared tunnel route dns songlo-oj oj.sarsed.eu.cc     # SAI
```

chạy xong với mã thoát `0`, nhưng dòng log ghi:

```
INF Added CNAME oj.sarsed.eu.cc which will route to this tunnel
    tunnelID=e1059c86-...        # <- tunnel KHÁC, không phải songlo-oj
```

cloudflared đọc `/root/.cloudflared/config.yml` — trong đó có dòng `tunnel:` của
một tunnel khác cùng tài khoản — và lấy tunnel từ **đó**, bất kể tên truyền vào.
Kết quả: một hostname mới bị gắn vào tunnel của dịch vụ khác. Bản ghi đó không
làm hỏng dịch vụ kia (ingress của nó không có hostname này nên trả 404), nhưng nó
là thay đổi ngoài ý muốn lên hệ thống đang chạy thật.

Phòng: truyền **cả** `--config` (trỏ tệp có `tunnel:` đúng) **và** uuid thay vì
tên. Hai lớp, vì thiếu một lớp là đủ để nó lặng lẽ dùng nhầm tunnel. Sau khi
chạy, **đọc lại dòng log và đối chiếu `tunnelID=`** với uuid mình muốn.

#### ⚠️ Thiếu `protocol: http2` thì tunnel `active` nhưng trả 530

Máy chủ chặn UDP ra ngoài thì QUIC — giao thức mặc định — không dial được:

```
ERR Failed to dial a quic connection error="failed to dial to edge with quic:
    timeout: no recent network activity"
```

systemd vẫn báo `active` vì tiến trình còn sống, nhưng **không có kết nối nào**
tới edge và Cloudflare trả **530 / lỗi 1033** cho mọi truy vấn. Đừng tin
`systemctl is-active`; kiểm tra kết nối thật:

```bash
journalctl -u songlo-tunnel --since '@'$(date -d '-2 min' +%s) --no-pager \
  | grep 'Registered tunnel connection'
# INF Registered tunnel connection connIndex=0 ... protocol=http2   <- đúng
```

Thiếu hẳn dòng đó thì dù `active` cũng chưa phục vụ được gì.

### Quick tunnel — chỉ để xem thử

Khi **chưa** có tên miền. **Phải trỏ `--config` vào một tệp riêng**:

```bash
mkdir -p /etc/songlo
printf 'url: http://127.0.0.1:8000\nprotocol: http2\n' > /etc/songlo/cloudflared.yml
cloudflared tunnel --config /etc/songlo/cloudflared.yml --url http://127.0.0.1:8000
```

Vì sao không được bỏ `--config`: nếu trên máy đã có tunnel có tên từ trước,
`/root/.cloudflared/config.yml` sẽ chứa `tunnel:` và `credentials-file:`.
cloudflared đọc tệp đó **kể cả khi đã truyền `--url`**, nên nó không tạo quick
tunnel mà đăng ký thêm một connector vào chính tunnel có tên của bạn. Ingress
của tunnel đó chỉ có hostname bạn đã cấu hình, nên mọi hostname khác trả **404**
— và bạn vừa vô tình thêm một connector vào hệ thống đang chạy thật. Triệu chứng
phân biệt: dòng `Settings:` trong `journalctl` có `credentials-file:`.

Địa chỉ `*.trycloudflare.com` **đổi mỗi lần khởi động lại** — không thể chọn,
không thể đăng ký, không mang sang lần sau. Chỉ dùng để xem thử.

## 7. Kiểm tra sau khi dựng

```bash
# Web trả lời
curl -I http://127.0.0.1:8000/

# Bộ chấm nhận việc và chấm được một bài
sudo -u songlo env $(cat /etc/songlo.env | xargs) \
    /opt/songlo/.venv/bin/python -m server.worker --once
```

Cần kiểm chứng hai thứ mà Windows không kiểm chứng được. Nộp một bài có vòng
lặp vô hạn và xem thời gian chạy báo về: nếu khoảng **1 giây** thì `RLIMIT_CPU`
hoạt động; nếu khoảng **5 giây** thì chỉ có đồng hồ canh giờ thực cắt được nó,
nghĩa là giới hạn CPU chưa có tác dụng. Kiểm tra thứ hai: trong lúc chấm, chạy
`ps -o user= -p $(pgrep -f 'sub[0-9]')` — phải thấy `songlo-judge`, không phải
`root`.

## 8. Sao lưu

Toàn bộ dữ liệu nằm trong `/var/lib/songlo`. Sao lưu bằng cách copy một tệp:

```bash
sudo -u songlo sqlite3 /var/lib/songlo/songlo.db ".backup /var/lib/songlo/backup-$(date +%F).db"
```

Dùng `.backup` chứ **không** `cp`: CSDL đang chạy ở chế độ WAL, nên `cp` chỉ tệp
chính sẽ cho ra một bản sao thiếu phần dữ liệu còn nằm trong nhật ký `-wal`.

Đặt lịch chạy hằng ngày bằng cron hoặc systemd timer, và **copy bản sao ra khỏi
máy chủ** — sao lưu nằm cùng đĩa với dữ liệu gốc thì không phải sao lưu.

## 9. Danh sách kiểm tra trước khi công bố

- [ ] `SONGLO_SECRET` đã đổi thành chuỗi ngẫu nhiên, không phải giá trị mặc định trong mã.
- [ ] Mật khẩu giáo viên đã đổi; mật khẩu học sinh không dùng chung một giá trị.
- [ ] `songlo-judge` là tài khoản riêng, không có quyền gì, không đăng nhập được.
- [ ] `SONGLO_JUDGE_RUNAS_UID`/`GID` đã đặt, và `ps` xác nhận mã học sinh chạy bằng tài khoản đó.
- [ ] `/var/lib/songlo/gendata` thuộc `songlo`, và **khác** `/var/lib/songlo/judge` (thuộc `root`).
- [ ] Đã thử sinh một bộ dữ liệu từ lời giải mẫu qua giao diện, trên chính máy chủ này.
- [ ] Đã tải một tệp bảng điểm về và **mở bằng Excel thật trên Windows**: chữ có
      dấu hiện đúng, các cột tách rời nhau (không dồn hết vào một cột), và Excel
      **không** hỏi gì về công thức. Đây là bước duy nhất không kiểm được bằng
      script — cả ba lỗi của tệp CSV đều im lặng, nên chỉ mắt người mới thấy.
- [ ] HTTPS đã bật.
- [ ] `/var/lib/songlo` không nằm trong bất kỳ thư mục nào được phục vụ tĩnh.
- [ ] Đã sao lưu thử và **phục hồi thử** một lần.
- [ ] `server/var/` trong repo vẫn bị `.gitignore` loại trừ (kiểm tra bằng
      `git check-ignore -v server/var/songlo.db`).
- [ ] Nếu bật phần nhờ AI viết: `SONGLO_AI_KEY` nằm trong `/etc/songlo.env` chứ
      **không** nằm trong mã nguồn, và `git check-ignore -v .env` xác nhận.
- [ ] `gunicorn` có `--timeout 120` (một lần nhờ AI viết mất ~20 giây, mặc định
      30 giây là quá sát), và `SONGLO_AI_TIMEOUT` nhỏ hơn giá trị đó.
- [ ] `MAX_TOTAL_SECONDS` trong `aiwriter.py` **nhỏ hơn** `--timeout` của
      `gunicorn` ít nhất 15 giây. Đây là ràng buộc giữa mã nguồn và cấu hình máy
      chủ: sửa một bên mà quên bên kia thì thử lại ba lần sẽ vượt thời hạn và
      giáo viên nhận 502 trắng.
- [ ] Đã thử **một lần thật**: dán một đề bài, bấm nhờ AI viết, rồi bấm sinh dữ
      liệu — và đọc lại mã trước khi bấm.
- [ ] Đã thử **đường hỏng**, không chỉ đường thành công: khi hết hạn mức, thông
      báo phải nói rõ còn bao lâu (chứ không phải "thử lại sau") và phải hiện ra
      trong vài giây. `_vps/step38_thu_lai.py` phần C làm việc này bằng một stub
      cục bộ, nên không tốn hạn mức thật.

## Giới hạn của cách ly

Nói thẳng để không ai yên tâm nhầm: cách ly ở đây **yếu hơn Docker**. Đã có
giới hạn bộ nhớ, giới hạn CPU, giới hạn số tiến trình, chặn tệp core, tách nhóm
tiến trình, và hạ quyền. **Chưa có** cách ly hệ thống tệp và chưa có cách ly
mạng: nếu worker chạy bằng tài khoản đọc được tệp nào thì mã học sinh cũng đọc
được tệp đó, và mã học sinh gọi ra Internet được.

Với một trường THCS, học sinh không có động cơ tấn công, nên mức này là hợp lý.
Nếu muốn chặt hơn mà không dựng Docker, thứ tự ưu tiên là: (1) chạy worker bằng
tài khoản riêng như trên, (2) thêm `RLIMIT_NOFILE`, (3) chặn mạng ra ngoài cho
tài khoản `songlo-judge` bằng `iptables -m owner`, (4) mới tới `bubblewrap`
hoặc `nsjail`.
