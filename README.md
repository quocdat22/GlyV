# GlyV

Công cụ thử nghiệm mở rộng font nhúng trong PDF để hỗ trợ tiếng Việt: trích xuất
stream font, dựng OTF tạm, kiểm tra glyph, vẽ dấu, duyệt ảnh và xuất font đã bổ sung.

Font nhúng thường là **subset**, chỉ chứa những glyph xuất hiện trong tài liệu.
Mỗi PDF có thể dùng bộ font khác nhau; thêm trang không đảm bảo bổ sung glyph
cho font đã trích xuất trước đó.

## Cài đặt

Cần Python 3 và môi trường hỗ trợ các thư viện trong [requirements.txt](requirements.txt).
Các lệnh dưới đây dành cho Linux/macOS, chạy từ thư mục gốc dự án:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Nếu `.venv` đã có, dùng lại môi trường đó. Các thư viện chính: fontTools, pikepdf,
Pillow, uharfbuzz và FontBakery.

## Cấu trúc thư mục

```text
input/                      PDF nguồn
scripts/                    Script xử lý và kiểm tra
artifacts/
  <bo-nguon>/
    fonts/                  Stream font gốc, chỉ đọc sau trích xuất
    otf/                    OTF tạm dựng từ stream font
    processed/<font>/       Hiệu chỉnh, ảnh và báo cáo riêng cho từng font
    logs/                   Log từng bước và từng họ font
    reports/                Tổng hợp trích xuất, kết quả và FontBakery
    build/                  OTF đầu ra của mọi font trong lần chạy
    templates.json          Bản mẫu vector của lần chạy
    manifest.json           Nguồn, SHA-256 và liên kết bản dựng
build/                      Bản sao OTF đã qua kiểm tra từ pipeline
CLAUDE.md                   Quy ước kỹ thuật và cách phối hợp
```

Tạo bộ artifact riêng cho mỗi nguồn hoặc lần thử cần lưu lại. Luôn truyền
`--run-dir`: nếu bỏ qua, hai script trích xuất/dựng OTF sẽ dùng thư mục gốc.
Dùng lại cùng thư mục có thể ghi đè kết quả; không chạy lại trích xuất vào bộ
stream gốc cần bảo toàn. Manifest chưa được tạo/cập nhật tự động ở mọi script.

## Chạy toàn bộ pipeline

Chạy tự động, bỏ bước dừng duyệt nhưng giữ toàn bộ artifact:

```bash
.venv/bin/python scripts/pipeline.py 'input/<nguon>.pdf' --run-dir 'artifacts/<lan-chay-moi>' --yes
```

Thay phần `<...>` trước khi chạy. Nếu không truyền `--run-dir`, pipeline tự tạo
thư mục theo thời gian UTC. Thư mục được chỉ định phải chưa tồn tại; pipeline
không ghi đè lần chạy cũ. Mặc định xử lý **tất cả font** trích xuất được. Dùng `--font '<ten-otf-khong-duoi>'`
chỉ khi muốn giới hạn một font.

Pipeline thực hiện trích xuất → dựng OTF tạm → đo và hiệu chỉnh riêng từng font →
vẽ dấu/râu/gạch → ghép font và dựng metrics → render HarfBuzz → FontBakery.
Sau kiểm thử, pipeline chép font có trạng thái `complete` hoặc `partial` vào
`build/*.otf` ở gốc dự án và ghi đường dẫn trong `exported_output` của manifest.
Font `partial` vẫn có thể thiếu ký tự; xem coverage trước khi dùng. File trùng tên
được thay thế bằng bản mới sau khi chép thành công; các file khác được giữ nguyên.
Khi dừng để duyệt hoặc font bị lỗi kiểm thử, pipeline không chép font đó vào đây.
Kết quả nằm trong cùng thư mục lần chạy:

- `build/`: font `.otf` đầu ra.
- `processed/<font>/sheets/render-harfbuzz.png`: ảnh render từ kết quả shape HarfBuzz.
- `processed/<font>/sheets/`: bảng glyph trước/sau, dấu riêng, mẫu dấu chồng, râu/gạch và SVG/JSON.
- `processed/<font>/calibration.json`: số đo nét, chiều cao, độ nghiêng và đường nét dấu đã hiệu chỉnh.
- `processed/<font>/reports/`: coverage trước/sau và tọa độ ghép.
- `fonts/`, `otf/`: stream nguồn và OTF tạm của các font được trích xuất/dựng thành công.
- `reports/`: kết quả trích xuất, tổng hợp từng font và FontBakery JSON theo từng họ font.
- `logs/`: stdout/stderr của từng bước, gồm log FontBakery.
- `manifest.json`: trạng thái từng bước, quyết định duyệt, nguồn, SHA-256 artifact
  và script; `templates.json` lưu mẫu vector gốc dùng cho lần chạy.

Muốn duyệt trước, bỏ `--yes`. Pipeline tạo mẫu rồi dừng ở trạng thái `awaiting_review`,
chưa xuất font cuối. Sau khi xem ảnh, tiếp tục:

```bash
.venv/bin/python scripts/pipeline.py --resume 'artifacts/<lan-chay-moi>' --yes
```

Resume kiểm tra nguồn, artifact và script không đổi từ lúc tạo mẫu. Nếu cần chỉnh
mẫu hoặc code, tạo lần chạy mới. Bỏ duyệt chỉ bỏ bước dừng, vẫn giữ mọi kiểm thử
và artifact. Khi có lỗi, pipeline trả mã khác 0, ghi trạng thái `failed` và giữ
log cùng các artifact đã tạo để chẩn đoán.

**Hiệu chỉnh tự động:** đo x-height, cap-height, độ rộng chữ tròn, độ dày nét và
độ nghiêng của từng font. Ưu tiên dấu sắc và dấu chấm có sẵn; nếu thiếu, điều chỉnh
mẫu vector theo số đo. Râu, gạch và dấu chồng được định vị theo đường nét của font
đó. Giữ style/weight, góc chữ nghiêng, caret slope và STAT tương ứng.

Pipeline hỗ trợ stream CFF và font OpenType/TrueType tĩnh; đường cong TrueType được
đổi sang CFF với sai số xấp xỉ tối đa UPM/1000. Chưa hỗ trợ Type 1 thô, variable font
hoặc tự suy diễn Unicode cho glyph CID không có ánh xạ. Những trường hợp không xử lý
được có trạng thái `unsupported`/`failed`, không làm dừng các font còn lại.

Thiếu chữ cơ sở thì bỏ qua các ký tự phụ thuộc và ghi rõ trong báo cáo. Font đó có
thể xuất OTF với trạng thái `partial`, không được coi là đủ 134 ký tự. Bản tổng hợp
nằm ở `reports/summary.json`; xem trạng thái từng font trong manifest trước khi dùng
file trong `build/`. Lỗi kỹ thuật hoặc font không hỗ trợ khiến mã thoát cuối là 1;
`partial` chỉ do thiếu chữ cơ sở có thể trả mã 0 và phải được kiểm tra qua báo cáo.

Mẫu dấu đi kèm là các hình học đơn giản trên lưới tham chiếu tùy ý, không phải
đường nét trích xuất từ font mẫu. Pipeline có thể dùng dấu gốc của font đầu vào
trong artifact cục bộ. Đây là hiệu chỉnh theo số đo, chưa thay thế việc duyệt
hình dáng bằng mắt. Dùng chế độ có duyệt nếu cần đánh giá thẩm mỹ trước khi ghép.

## Chạy từng bước: trích xuất và kiểm tra font

Thay mọi phần `<...>` bằng đường dẫn/tên phù hợp trước khi chạy.

**1. Trích xuất font nhúng từ PDF:**

```bash
.venv/bin/python scripts/extract_fonts.py 'input/<nguon>.pdf' --run-dir 'artifacts/<bo-nguon>'
```

**2. Dựng OTF tạm:**

```bash
.venv/bin/python scripts/build_otf.py --run-dir 'artifacts/<bo-nguon>'
```

Script trích xuất hỗ trợ các stream FontFile/FontFile2/FontFile3; bước dựng OTF
xử lý CFF và font OpenType/TrueType tĩnh. Kiểm tra log từng font: dòng `FAIL` có thể xuất hiện dù
script kết thúc với mã thoát thành công.

**3. Liệt kê ký tự tiếng Việt còn thiếu:**

```bash
mkdir -p 'artifacts/<bo-nguon>/reports'
.venv/bin/python scripts/vietnamese_coverage.py 'artifacts/<bo-nguon>/otf/<font>.otf' > 'artifacts/<bo-nguon>/reports/coverage.json'
```

Báo cáo JSON chứa đủ danh sách ký tự, mã Unicode, tên Unicode, glyph tương ứng,
số ký tự có/thiếu và các nguyên âm Latin trơn còn thiếu.

Bộ **134 ký tự** được sinh bằng `unicodedata`, chuẩn hóa NFC: 12 dạng nguyên âm
tiếng Việt × 6 thanh × 2 kiểu hoa/thường, cộng Đ/đ, trừ 12 nguyên âm Latin trơn
`A E I O U Y a e i o u y`. Đây không phải tổng số glyph của font.

## Vẽ dấu và dựng bản tiếng Việt

1. Xem toàn bộ glyph từ OTF, kể cả biến thể không có ánh xạ Unicode.
2. Vẽ sắc, huyền, hỏi, ngã, nặng, mũ, trăng, râu và gạch theo nét font nguồn.
   Tận dụng dấu gốc; chỉ dùng glyph cơ sở đang có.
3. Lưu SVG/JSON và ảnh PNG vào `sheets/`. Duyệt dấu riêng, râu, gạch, chữ hoa/thường
   và tổ hợp dấu chồng trước khi ghép.
4. Ghép ký tự còn thiếu, xử lý chấm trên `i`, khoảng hở quanh râu và dấu chồng.
   Dựng lại metrics/name/cmap; xuất `build/<font>-Vietnamese.otf`.
5. Render bằng HarfBuzz, xem ảnh, chạy FontBakery và lưu báo cáo cùng SHA-256.

Các script vẽ và dựng bản tiếng Việt dùng chung kết quả đo của `scripts/calibration.py`.
Pipeline truyền đường dẫn và thông số riêng cho từng font; khi chạy riêng, đọc
đường dẫn mặc định trước khi chạy.
Với OTF/CFF, các thành phần được ghép rồi lưu thành đường nét Type 2 hoàn chỉnh,
không phải composite trong bảng TrueType `glyf`.

## Kiểm thử đầu ra

- Đối chiếu 134 ký tự, ghi rõ phần còn thiếu do thiếu chữ cơ sở; giữ đường nét glyph gốc.
- Metrics dọc bao phủ dấu cao nhất và phần thấp nhất, tránh cắt glyph.
- HarfBuzz cho kết quả tương đương giữa NFC và NFD của các ký tự có trong bản dựng.
- Ảnh render kiểm tra dấu chồng, râu, gạch và chữ hoa/thường.

Chạy FontBakery profile OpenType và lưu báo cáo. Khi có nhiều style cùng họ,
truyền các file đó trong cùng lệnh; các họ khác nhau phải kiểm tra riêng:

```bash
.venv/bin/fontbakery check-opentype 'build/<font>-Vietnamese.otf' --skip-network --no-progress --no-colors --json 'artifacts/<bo-nguon>/reports/fontbakery.json'
```

FontBakery có thể báo lỗi công cụ với subset quá nhỏ (chẳng hạn CFF chỉ có glyph
đầu dòng); pipeline giữ nguyên lỗi và artifact, không bỏ kiểm tra để báo thành công.
Xem [CLAUDE.md](CLAUDE.md) để biết quy ước kỹ thuật chi tiết.

Kiểm tra code điều phối, bảo toàn stream, kiểm tra hiệu chỉnh và resume:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Phạm vi sử dụng

Đây là bản thử nội bộ; chưa bổ sung hinting/kerning và không khôi phục toàn bộ
glyph của font thương mại. Hỗ trợ NFC/NFD đã kiểm tra không đồng nghĩa hỗ trợ
mọi tổ hợp combining mark ngoài bộ tiếng Việt.

Giữ nguyên PDF, stream nguồn và thông tin bản quyền. Không phân phối hoặc đưa
font thương mại lên repo công khai; kiểm tra EULA trước khi sử dụng ngoài nội bộ.

## Chuẩn bị publish GitHub

Chỉ đưa mã nguồn, tài liệu và mẫu hình học trong `scripts/profiles/templates.json`
lên repo. PDF, font nguồn/đầu ra, ảnh render, SVG đường nét, log và manifest
chứa dữ liệu nguồn phải giữ trong các thư mục cục bộ đã được bỏ qua.
Không dùng `git add -f` để đưa những file này lên Git. Các kiểm thử tự sinh
font và PDF hình học tạm, không cần tài liệu hoặc font thương mại.

`.gitignore` không xóa dữ liệu trong commit cũ. Nếu lịch sử phát triển có tên
hoặc dữ liệu mẫu riêng tư, hãy publish từ một bản sao chỉ chứa mã nguồn đã
kiểm tra, khởi tạo Git mới, không sao chép `.git/` cũ. Không đẩy lịch sử cũ
hoặc dùng `git push --mirror` từ thư mục phát triển.
