# 📖 Hướng Dẫn Sử Dụng: Siêu Bot Đa Vũ Trụ (All-In-One Discord Bot)

Chào mừng bạn đến với Cẩm nang Vận hành Siêu Bot tối thượng! Tài liệu này không chỉ phác họa cơ chế hoạt động mà còn là Cuốn Từ Điển "thần thánh" tra cứu toàn bộ các dòng Lệnh (Command) dắt túi để bạn dễ dàng làm chủ Máy Thống Trị Discord.

---

## 🛠️ PHẦN 1: Chuẩn Bị & Khởi Động Động Cơ

### 1. Nguyên vật liệu cần thiết
Đảm bảo máy chủ (máy tính) của bạn đã cài đặt những thứ sau:
*   **Python:** Cài đặt bản mới nhất.
*   **Bộ Não Cài Đặt (Modules):** Cài đầy đủ `discord.py`, `PyNaCl`, `yt-dlp`, `customtkinter`, `Pillow`, `psutil`.
*   **Bộ Loa Phát Thanh (FFMPEG):** Có sẵn tệp `ffmpeg.exe` ném cục bộ ở thư mục chứa mã nguồn hoặc cấu hình hệ thống.

### 2. Trạm Kích Hoạt (Phần Mềm GUI)
Trọng tâm phần mềm nằm ở **Bảng Điều Khiển Cứng (`setting_gui.py`)**. Bạn chẳng cần nặn tay chạm vào dòng code nào:
1.  Bấm vào Icon Chạy hoặc Nhập terminal: `python setting_gui.py`
2.  Bảng Ứng Dụng Nổi hiện ra. Ở Tab đầu tiên, bạn Dán **Discord Bot Token** của bạn vào.
3.  Cấu hình Tiền tố lệnh (Prefix) mong muốn (Ví dụ: dấu `!`).
4.  Cài đặt Ảnh nền Rank, chèn khung tọa độ theo ý thích. Đăng ký tên Server, thiết lập Rule của riêng Server đó.
5.  Sang Tab **Social Media** nếu muốn Cắm Ăng-ten theo dõi kênh Youtube, nền tảng.
6.  Ấn Bấm Nút Xanh **[▶ CHẠY BOT]** to chà bá. XONG! Sóng đã được kết nối!

---

## 📢 PHẦN 2: Cuốn Sách Gọi Lệnh (Lệnh Dành Cho Dân Thường)
*(Trong ví dụ này, tiền tố mặc định là dấu chấm than `!`. Tuy nhiên, mọi lệnh này bạn hoàn toàn tự ý Sửa chữa "Định danh" ở trong Phần Mềm GUI).*

### Nhóm Lệnh 🎵 Âm Nhạc & Giải Trí
*   `!play <Liền kết Youtube / Tên bài hát>`: Gọi Bot vào Trạm Voice hiện tại và quẩy nhạc. Quăng link hoặc tên chả ăn nhằm, Bot sẽ tự động Tìm bắt và xướng kênh.
*   `!skip`: Nhảy bài hiện tại (Bot sẽ chơi nháy bài tiếp theo trong Hàng Đợi).
*   `!pause`: Trì hoãn sự hưng phấn - Tạm thời Ngừng chạy.
*   `!resume`: Bơm tiếp nhiên liệu - Bot chơi nhạc nối tiếp đoạn vừa dừng.
*   `!stop`: Bắt Bot ngưng ca hát vĩnh viễn, tát nước đẩy ra khỏi Trạm.
*   `!ping`: Kiểm tra kết nối sóng Wifi nội bộ giữa Bot và Trái Đất (Đo trễ ms).

### Nhóm Lệnh 💸 Tài Chính & Chứng Minh Thư
*   `!daily`: Rải thảm lương mỗi 24 giờ. Gọi ra để lĩnh ngay `200 Vàng`.
*   `!bank`: Check ví tiền! Mở tung Sổ Sáp Nhập Tài Khoản hiển thị số dư, cấp độ.
    *   *Tính năng Siêu Đỉnh: Lệnh Bank đính kèm cả một Mini-Shop. Click vào "Lắc Tài Xỉu" để đỏ đen tiền hoặc Bỏ Tiền mua danh hiệu Role màu chói lóa.*
*   `!rank` hoặc `!rank @Tên_Ai_Đó`: Yêu cầu in ra Thẻ Cấp Độ Siêu Đẹp! (Chữ nghệ thuật, Custom thẻ đính hình Avatar đục lỗ).

### Nhóm Lệnh 🎙️ Cá Nhân Hóa (Bất cứ ai cũng dùng được)
*   `!myvoice <Tự_Đặt_Tên_Được>`: Không cần bấm nút làm phiền Admin, lệnh này Tự móc nối 1 căn hầm Kéo Kênh Riêng cho chính bạn. Bạn độc quyền làm Vua kênh (đổi tên, đuổi cổ). Kênh tự hủy sau 60s tính từ vòng không còn ma nào.

---

## 🛡️ PHẦN 3: Lệnh Quân Cảnh Của Giám Đốc (Role Mod / Admin)

Máy Trạm cho phép Đội Tuần Tra Kỷ Luật sử dụng các Quyền uy chấn phái. (Dành ra cho ai có quyền gốc `Administrator` TRONG DISCORD Hoặc ai Đang khoác cái Role Mod bạn config riêng qua ứng dụng `setting_gui`).

### Nhóm Cày Đặt Khóa An Toàn 🚧
*   `!ticket_setup`: Tranh Tường Khuy Bấm Khiếu Nại. Bắn ra một Giao diện Nút ở kênh Chat. Bất kỳ dân đen nào click lên thì Bot tự mở Phòng Riêng Bí Mật kéo hắn và Mod vào giải quyết tranh cãi.
*   `!setup_voice`: Ném Ra Bảng Thu thập Đơn Triệu Hồi Kênh. Thay vì gõ lệnh, ai thích ấn Nút thì tự mở Pop-Up Đăng ký tên Phòng Riêng Voice Mới.

### Nhóm Tòa Án Phán Xét ⚖️
*   `!kick @Tội_Phạm [Lý Lý do]`: Búng tay sút đít bay vào Hư Không (Rời nhóm tức thời).
*   `!ban @Tội_Phạm [Lý Lý do]`: Cấm Cửa Mãi Mãi (Cách ly vĩnh viễn).
*   `!mute @Tội_Phạm <Số_Phút> [Lý do]`: Dùng Cây Đập Ruồi Khoá Mõm timeout. Vi phạm xạo láo thì nhét giẻ vào họng tức tốc.
*   `!clear <Số Lượng>`: Xe Quét rác dạt dẹt Lên hàng loạt Tin Rác. (VD: `!clear 10` xóa lẹ làng 10 tin nhắn rác cuối cùng).
*   `!addword <từ_lóng>`: Nạp Ngôn từ Rác cấm nói vào AutoMod. (Ví dụ: `!addword đm`). Bất cứ ai sủa ra chữ này, tin nhắn bị Auto Delete.
*   `!delword <từ_lóng>`: Xóa Ngôn từ Rác đó ra khỏi Sổ Bôi Đen.

### Nhóm Siêu Trạm Bắt Sóng Mạng Xã Hội 📡 (Radar)
Cỗ Máy Rì-Rầm quét nền ngầm mỗi 5 phút! Nếu Mạng Youtube, Tiktok chớm có Clip mới, Bot đánh hơi thấy sẽ rải Tin vào Channel bằng Khung Nút Tương tác đẳng cấp.
*   `!add_social <Tên_Mạng> <Link_Kênh> <#Kênh_Nhận> [@Tag_Ví_Dụ]`: Đầu tư gắn 1 ăng-ten vào theo dõi kênh chỉ định.
    *   *Nền Tảng Hỗ Trợ: `youtube`, `reddit`, `tiktok`, `facebook`.*
    *   *Ví Dụ:* `!add_social youtube UCx... #tin-tuc @everyone`.
*   `!rm_social <Tên_Mạng> <Link_Kênh>`: Chém đứt ăng ten, hủy bám đuôi mục tiêu ngứa mắt.
*   `!list_social`: Báo Nhanh Check Toàn Diện Hệ Thống Rada đang Căng Nóc bắt điện đàm những Mạng nào trong sever!

---

*Hết.*
**Sẵn sàng Phá Đảo thế giới với Vũ Khí Tối Thượng rồi, khởi chạy thôi!**
