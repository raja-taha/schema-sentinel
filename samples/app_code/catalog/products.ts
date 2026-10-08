// Frontend / BFF query still treats sku as string
export async function getProductBySku(sku: string) {
  const q = `SELECT id, sku, name FROM products WHERE sku = '${sku}'`;
  return q;
}
