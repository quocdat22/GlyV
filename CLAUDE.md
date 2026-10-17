# Dự án: mở rộng font hỗ trợ tiếng Việt

## Mục tiêu và trạng thái
Trích xuất font nhúng từ PDF, kiểm tra glyph có sẵn và dựng bản hỗ trợ tiếng Việt
phục vụ thử nghiệm nội bộ. Font nhúng thường là subset; không mặc định rằng mọi
PDF có cùng họ font, hoặc PDF nhiều trang hơn sẽ chứa đủ glyph của font trước đó.

Đã có quy trình trích xuất, dựng OTF tạm, xem bảng glyph, thống kê ký tự thiếu,
vẽ và duyệt dấu, ghép đường nét, dựng metrics và kiểm thử font đầu ra.

## Ràng buộc
- Font nguồn có bản quyền; chỉ dùng nội bộ. Không phân phối hoặc đưa font lên repo
  công khai. Kiểm tra EULA trước khi dùng ngoài nội bộ.
- PDF và stream font gốc là dữ liệu nguồn: không sửa hoặc ghi đè.
- Giữ nguyên đường nét, ánh xạ Unicode và advance của glyph gốc, kể cả glyph
  đặc biệt, biến thể không có Unicode và ligature.
- Chỉ dựng trên glyph cơ sở đang có. Nếu thiếu glyph cơ sở, báo rõ; không tự lấy
  chữ từ font khác để thay thế.
- Không yêu cầu hinting/kerning hoàn hảo cho bản thử; không coi subset đã mở rộng
  là toàn bộ bộ font thương mại.

## Cấu trúc hiện tại
- `input/`: PDF nguồn.
- `scripts/`: script trích xuất, dựng font, kiểm tra coverage và vẽ mẫu.
- `artifacts/<bo-nguon>/`: tách biệt artifact theo PDF nguồn hoặc lần chạy.
  - `fonts/`: stream nhúng gốc, chỉ đọc sau khi trích xuất.
  - `otf/`: OTF tạm để đọc glyph và render.
  - `processed/<font>/`: `calibration.json`, `sheets/`, `reports/` riêng cho từng font.
  - `reports/`: tổng hợp trích xuất, trạng thái từng font và FontBakery theo họ font.
  - `logs/`: log các bước dùng chung và các bước của từng font.
  - `build/`: mọi OTF đầu ra của lần chạy.
  - `templates.json`: bản mẫu vector được lưu cùng lần chạy.
  - `manifest.json`: nguồn, SHA-256 và liên kết bản dựng khi có.
- `build/`: OTF đầu ra và hướng dẫn dựng lại.
- `.venv/`: môi trường Python của dự án.

Không dùng chung `fonts/`, `otf/`, `sheets/` ở gốc cho các bộ nguồn mới.
Tạo thư mục mới nếu cần giữ riêng từng lần thử. Tham số `--run-dir` mặc định là
`.` để tương thích cách gọi cũ; dùng lại cùng thư mục có thể ghi đè kết quả.
Các script vẽ và dựng dùng chung `scripts/calibration.py` để đo mỗi font và điều
chỉnh mẫu vector trong `scripts/profiles/templates.json`. Các đường dẫn mặc định
của script chạy riêng vẫn dùng cho tương thích; pipeline truyền đường dẫn của lần
chạy mới, không đụng artifact cũ.

## Chạy pipeline tự động hoặc có duyệt

- `scripts/pipeline.py <pdf> --run-dir <thu-muc-moi> --yes`: chạy hết, không dừng duyệt,
  vẫn lưu mọi artifact và chạy đủ kiểm thử. Đây là chế độ người dùng đã cho phép.
- Bỏ `--yes`: tạo mẫu và dừng ở `awaiting_review`, chưa dựng font cuối.
- `scripts/pipeline.py --resume <thu-muc-lan-chay> --yes`: tiếp tục sau khi duyệt;
  yêu cầu nguồn, artifact và script không đổi. Nếu cần sửa, tạo lần chạy mới.
- Có thể bỏ `--run-dir` để dùng thư mục có timestamp; thư mục chỉ định phải chưa tồn tại.
- Mặc định hiệu chỉnh và mở rộng mọi font trích xuất được; `--font` chỉ giới hạn một font khi được yêu cầu.
- Font cuối nằm trong `build/` của lần chạy; ảnh HarfBuzz và tọa độ ghép nằm trong
  `processed/<font>/sheets/` và `processed/<font>/reports/`. Số đo/dấu hiệu chỉnh nằm
  trong `processed/<font>/calibration.json`. Pipeline tự cập nhật manifest và SHA-256.
- Sau kiểm thử, pipeline chép font `complete`/`partial` vào `build/*.otf` ở gốc dự án,
  thay thế file trùng tên và ghi `exported_output` trong manifest; không chép font lỗi.
- Lỗi của một font không chặn các font còn lại. Mã thoát cuối khác 0 nếu có lỗi kỹ
  thuật/font không hỗ trợ; giữ toàn bộ artifact. Font thiếu chữ cơ sở có thể trả mã 0
  nhưng phải ghi `partial`, liệt kê ký tự thiếu, không báo đủ 134/134.
- FontBakery chạy theo từng họ font, kiểm tra các style cùng họ trong cùng lệnh.
  Lưu kết quả trong `reports/fontbakery-family*.json` và liên kết từ manifest.

## Quy trình làm việc
Chạy lệnh từ thư mục gốc bằng `.venv/bin/python`.
Các đường dẫn trong dấu `<...>` dưới đây là placeholder cần thay trước khi chạy.

1. Trích xuất vào một bộ artifact mới:
   ```bash
   .venv/bin/python scripts/extract_fonts.py 'input/<nguon>.pdf' --run-dir 'artifacts/<bo-nguon>'
   ```
2. Dựng OTF tạm từ các stream CFF của bộ đó:
   ```bash
   .venv/bin/python scripts/build_otf.py --run-dir 'artifacts/<bo-nguon>'
   ```
   Script dựng OTF hỗ trợ CFF và font OpenType/TrueType tĩnh; đường cong bậc hai
   được đổi sang CFF với sai số tối đa UPM/1000. Chưa xử lý Type 1 thô, variable
   font hoặc tự suy diễn Unicode cho CID không có ánh xạ. Đọc log từng font; không chỉ dựa vào mã thoát của script.
3. Đọc glyph order và `cmap` từ OTF; xuất bảng đủ mọi glyph, kể cả glyph chưa có
   ánh xạ Unicode. Không suy ra coverage chỉ bằng mắt từ ảnh.
4. Sinh và đối chiếu bộ 134 ký tự:
   ```bash
   .venv/bin/python scripts/vietnamese_coverage.py 'artifacts/<bo-nguon>/otf/<font>.otf'
   ```
   Script in JSON ra stdout. Lưu báo cáo trong `reports/` của bộ nguồn tương ứng.
5. Vẽ sắc, huyền, hỏi, ngã, nặng, mũ, trăng, râu và gạch theo nét của từng font,
   từng weight. Tận dụng dấu gốc nếu có. Lưu đường nét chỉnh sửa được bằng
   SVG/JSON và ảnh PNG: dấu riêng, chữ hoa/thường, tổ hợp dấu chồng, mẫu cỡ nhỏ.
6. Xuất ảnh để người dùng duyệt hình dáng và vị trí trước khi ghép, trừ khi đã chọn
   chế độ tự động `--yes`. Chế độ tự động vẫn xuất và giữ toàn bộ mẫu để xem lại.
   Khi người dùng yêu cầu ghép sau vòng duyệt, tiếp tục theo phạm vi đã được cho phép.
7. Dựng ký tự còn thiếu, hiệu chỉnh metrics/name/cmap và xuất
   `build/<font>-Vietnamese.otf`. Lưu tọa độ thành phần và thông số vào báo cáo build.
8. Kiểm thử rồi cập nhật báo cáo, SHA-256 và liên kết bản dựng trong manifest.
   Việc tạo/cập nhật manifest không tự động có ở mọi script; kiểm tra sau mỗi bước.

## Quy ước ghép và metrics
- Giữ UPM của font nguồn; mẫu hình học được đổi tỷ lệ theo số đo mỗi font.
- Sinh ký tự bằng `unicodedata` và chuẩn hóa NFC, không gõ tay danh sách 134 ký tự.
  Bộ này gồm 12 dạng nguyên âm tiếng Việt với sáu thanh, cả hoa và thường, cộng
  Đ/đ, trừ 12 nguyên âm Latin trơn `A E I O U Y a e i o u y`.
- Tên glyph theo Adobe Glyph List nếu có, nếu không dùng `uniXXXX`.
- Với CFF/Type 2, ghép thành phần theo tọa độ rồi lưu đường nét hoàn chỉnh;
  không dùng cơ chế composite của bảng TrueType `glyf`.
- Đo chiều cao chữ, độ rộng chữ tròn, nét đứng và góc nghiêng của từng font; tận dụng
  dấu sắc/chấm nguồn nếu có, nếu không điều chỉnh mẫu vector. Đây là hiệu chỉnh theo
  số đo, không đảm bảo tương đương thiết kế thủ công cho mọi font.
- Chữ hoa cần vị trí và tỷ lệ dấu riêng. Đo bounds để tính khoảng hở giữa thân,
  mũ/trăng, dấu thanh và râu. Các tỷ lệ đã dùng trong bản thử là thông số hiệu
  chỉnh riêng, không phải quy tắc chung cho mọi font.
- Khi thêm dấu thanh phía trên `i`, bỏ chấm gốc; với dấu nặng giữ chấm phía trên.
- Điều chỉnh advance nếu râu vượt chiều rộng cũ; giữ khoảng hở bên phải.
- Tính lại side bearings, bounds, hhea, OS/2, độ cao chữ, Unicode/codepage ranges
  và name/CFF metadata. Giữ weight, style và góc nghiêng; đặt caret slope và STAT
  đúng với từng bản dựng. Ascender/descender phải bao phủ dấu cao nhất, dấu nặng
  và descender thấp nhất để tránh bị cắt.
- Giữ thông tin bản quyền nguồn. Nếu cần chuẩn hóa chuỗi CFF sang ASCII, bảo toàn
  nội dung bản quyền; không tự gán giấy phép mới.

## Kiểm thử bắt buộc khi dựng font
- Mở lại OTF đã lưu; đối chiếu đủ 134 ký tự. Ký tự không dựng được chỉ được bỏ qua
  khi thiếu chữ cơ sở và phải ghi rõ trong coverage; glyph hiện có không trỏ `.notdef`.
- Kiểm tra đường nét glyph gốc không đổi và metrics dọc bao phủ mọi glyph.
- Shape mọi ký tự dựng được và chuỗi thử bằng HarfBuzz ở cả NFC lẫn NFD; so sánh glyph ID,
  advance và offset. Kiểm tra này dành cho bộ tiếng Việt đã dựng, không cam kết
  hỗ trợ mọi tổ hợp combining mark ngoài bộ đó.
- Render theo kết quả HarfBuzz ra PNG, xem bằng mắt chữ hoa/thường, i có dấu,
  râu, gạch và dấu chồng. Không chỉ kiểm tra font nạp được.
- Chạy FontBakery profile OpenType theo từng họ font, lưu log và JSON trong `reports/`.
  Báo rõ PASS/SKIP/FAIL/ERROR/WARN; không che lỗi công cụ bằng cách bỏ qua kiểm tra.
- Đối chiếu hash dữ liệu nguồn và ghi SHA-256 đầu ra để quản lý artifact.

Chuỗi thử:
```text
Ắ ằ ẳ ẵ ặ Ấ ầ ẩ ẫ ậ Ơ ờ ở ỡ ợ Ư ừ ử ữ ự Đ đ
Thuận gió hòa, người Việt Nam yêu đất nước.
THUẬN GIÓ HÒA, NGƯỜI VIỆT NAM YÊU ĐẤT NƯỚC.
```

## Công cụ và cách phối hợp
- Thư viện hiện có: fontTools, pikepdf, Pillow, uharfbuzz, fontbakery.
- Dùng đường nét vector cho glyph; tái sử dụng helper và dữ liệu đã có.
- Chạy script và xem ảnh render thay vì đoán kết quả.
- Dừng ở ảnh duyệt khi người dùng yêu cầu xem trước; không tự ghép hoặc thay
  bản dựng đã duyệt trong bước đó.
- Hỏi trước khi sửa hàng loạt hoặc xóa file nếu chưa được yêu cầu/cho phép.
- Trong hướng dẫn chung, dùng placeholder và mô tả theo vai trò; không ghi tên
  PDF, tên file mẫu hoặc tên font đã dùng khi phát triển.

## Dữ liệu khi publish

- Dùng tên chung cho script, ví dụ và đường dẫn mặc định; không ghi tên mẫu phát triển.
- Mẫu hình học công khai không chứa đường nét trích xuất từ font đầu vào.
- Giữ artifact, font và tài liệu nguồn ngoài Git, kể cả ảnh và dữ liệu vector.
- Kiểm tra cả lịch sử Git trước khi publish; ignore không loại dữ liệu đã commit.
