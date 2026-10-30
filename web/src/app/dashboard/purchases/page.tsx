import { PurchaseTable } from "@/components/PurchaseTable";
import { listPurchases } from "@/lib/api";

export const dynamic = "force-dynamic";

// PBL-aegis 감사 대시보드의 "거래" 화면과 같은 구성.
export default async function PurchasesPage() {
  const records = await listPurchases();
  return (
    <>
      <div className="pageHead">
        <p className="eyebrow">거래 기록</p>
        <h1>전체 요청·결제 기록</h1>
        <p>각 요청의 선택 결과와 결제 결과를 함께 확인합니다.</p>
      </div>
      <section className="panel">
        <PurchaseTable records={records} />
      </section>
    </>
  );
}
