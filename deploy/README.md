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
```

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
    --access-logfile - --error-logfile - \
    "server.app:app"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/songlo-judge.service`:

```ini
[Unit]
Description=Song Lo OJ - cham bai
After=network.target

[Service]
# Chạy bằng root để hạ được quyền tiến trình con xuống songlo-judge.
# Nếu chạy bằng songlo thì mã học sinh chạy cùng quyền với worker, và
# RLIMIT_NPROC sẽ tính chung vào hạn mức tiến trình của tài khoản đó.
User=root
EnvironmentFile=/etc/songlo.env
Environment=SONGLO_JUDGE_RUNAS_UID=<uid của songlo-judge>
Environment=SONGLO_JUDGE_RUNAS_GID=<gid của songlo-judge>
Environment=SONGLO_JUDGE_MAX_PROCS=64
WorkingDirectory=/opt/songlo
ExecStart=/opt/songlo/.venv/bin/python -m server.worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Thay `<uid>` và `<gid>` bằng số lấy từ `id songlo-judge` ở bước 2.

```bash
sudo chmod 600 /etc/songlo.env
sudo systemctl daemon-reload
sudo systemctl enable --now songlo-web songlo-judge
sudo systemctl status songlo-web songlo-judge
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
- [ ] HTTPS đã bật.
- [ ] `/var/lib/songlo` không nằm trong bất kỳ thư mục nào được phục vụ tĩnh.
- [ ] Đã sao lưu thử và **phục hồi thử** một lần.
- [ ] `server/var/` trong repo vẫn bị `.gitignore` loại trừ (kiểm tra bằng
      `git check-ignore -v server/var/songlo.db`).

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
