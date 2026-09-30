"""Song Lo OJ — hệ thống chấm bài lập trình cho Trường THCS Sông Lô.

Các mô-đun:

``db``          kết nối SQLite, khởi tạo lược đồ, tiện ích thời gian
``auth``        đăng nhập, phiên làm việc, phân quyền, chống CSRF
``sandbox``     chạy tiến trình con với giới hạn thời gian và bộ nhớ
``judge``       dịch bằng g++, chạy từng bộ dữ liệu, phân loại kết quả
``worker``      tiến trình nhận bài nộp từ hàng đợi và gọi ``judge``
``app``         ứng dụng Flask: các tuyến đường
``seed``        tạo CSDL và dữ liệu mẫu
"""

__version__ = "1.0.0"
