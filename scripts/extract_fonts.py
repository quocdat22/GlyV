"""Trích xuất font nhúng (FontFile/FontFile2/FontFile3) từ PDF.

Chạy:  python extract_fonts.py input/sample.pdf --run-dir artifacts/sample
Kết quả: fonts/<TÊN>_FontFile3.bin (stream gốc, KHÔNG sửa các file này).
"""
import argparse, os, pikepdf

def main(pdf_path, out_dir="fonts"):
    os.makedirs(out_dir, exist_ok=True)
    pdf = pikepdf.open(pdf_path)
    n = 0
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Dictionary) and obj.get("/Type") == "/FontDescriptor":
            name = str(obj.get("/FontName")).lstrip("/")
            if not name or os.path.basename(name) != name or "\\" in name or name in (".", ".."):
                raise ValueError(f"Tên font không hợp lệ: {name!r}")
            for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                if key in obj:
                    data = obj[key].read_bytes()
                    fn = f"{out_dir}/{name.replace('+', '_')}{key.replace('/', '_')}.bin"
                    if os.path.exists(fn):
                        with open(fn, "rb") as existing:
                            if existing.read() != data:
                                raise ValueError(f"Stream trùng tên nhưng khác nội dung: {fn}")
                        continue
                    with open(fn, "xb") as output:
                        output.write(data)
                    print(f"{name:40s} {key:11s} {len(data):7d} bytes -> {fn}")
                    n += 1
    print(f"Đã trích xuất {n} font stream.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--run-dir", default=".", help="Thư mục chứa artifact của một lần chạy")
    args = parser.parse_args()
    main(args.pdf, os.path.join(args.run_dir, "fonts"))
