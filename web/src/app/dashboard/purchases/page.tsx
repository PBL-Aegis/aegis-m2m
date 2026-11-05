import { PurchaseList } from "@/components/PurchaseList";
import { listPurchases } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PurchasesPage() {
  const records = await listPurchases();
  return (
    <div className="page tight">
      <h1>전체 기록</h1>
      <PurchaseList records={records} />
    </div>
  );
}
