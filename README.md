# CPD Big Data — Python CSV Extractor

ดึงสถิติสหกรณ์จาก https://bigdata.cpd.go.th/ ผ่าน API ที่ Angular Frontend เรียกใช้ บันทึกเป็น CSV พร้อม Raw JSON

## รันคำสั่งเดียว

ต้องมี Python 3.9+ แล้วเปิด PowerShell/Terminal ที่ root ของ repo:

    python main.py

ไม่มี third-party dependencies ไม่ต้อง pip install

ปีเริ่มต้นคือ พ.ศ. ปีที่แล้ว (2568 หากรันในปี ค.ศ. 2026) และ sector=0 (ทั้งหมด)

## Options

    python main.py --year 2568 --sector 1
    python main.py --year 2568 --sector 2 --summary-only
    python main.py --dry-run
    python main.py --out D:\cpd_output

sector: 0 = ทั้งหมด, 1 = ภาคการเกษตร, 2 = นอกภาคการเกษตร

## Output

- output/cpd_summary.csv — สหกรณ์ Active/Non-active, สมาชิก, กรรมการ และเจ้าหน้าที่แยกชาย/หญิงและยอดรวม
- output/cpd_type.csv — จำนวนสหกรณ์แยกประเภท
- output/cpd_strength.csv — จำนวนสหกรณ์ตามประเภทและระดับความเข้มแข็ง
- output/cpd_province.csv — จำนวนสหกรณ์รายจังหวัด
- output/cpd_request_log.csv — สถานะ Request และ error
- output/raw/<timestamp>/*.json — JSON ต้นฉบับแยกตามการรัน

CSV บันทึก UTF-8 BOM เพื่อเปิด Excel ได้ หาก API ใดล้มเหลวโปรแกรมคืน exit code 1 พร้อม error log โดยไม่เติม 0 ปลอม

## API และข้อจำกัด

- Base URL จาก JavaScript: https://bigdata_api.cpd.go.th/apitest/
- POST JSON Body (สามค่าเป็น string): OrgOrgId='null', PhakId='null', KhetId='null'
- สมาชิก/กรรมการ/ประเภท/ความเข้มแข็ง รับ Query year และ sector 0/1/2
- เจ้าหน้าที่รับ Query year และ sector เป็น null หรือข้อความภาษาไทยตามตัวกรอง
- จำนวนสหกรณ์กับข้อมูลแผนที่ไม่ได้ส่ง year/sector ในต้นฉบับ; ตัวเลขเหล่านี้อาจไม่ผูกกับปีที่เลือก CSV จะแสดง flag ว่าไม่ถูกกรอง
- selected_year_be คือปีที่เลือก ไม่ใช่วันที่ Backend รับรองข้อมูล; retrieved_at_ict คือเวลาที่ดึงจริง
- มี timeout, retry เฉพาะ network/429/5xx, หน่วง request, SSL verification ค่าเริ่มต้น
- ใช้เฉพาะข้อมูลที่เปิดให้เข้าถึงได้ตามเงื่อนไขเว็บไซต์ และไม่ข้ามระบบยืนยันตัวตน

## Tests (ไม่เรียก API)

    python -m unittest discover -s tests -v

ชุดทดสอบจำลอง Response โดยไม่ยืนยันความสำเร็จของ Backend สด ต้องทดสอบจริงในเครือข่ายที่เข้าถึง CPD ได้
