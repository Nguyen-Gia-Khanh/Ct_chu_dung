import type { Column, ContentRow, ProductRow } from "./types";

export const stockText = (stock: number | null | undefined) => (stock === null || stock === undefined ? "Unknown" : stock);

export const idColumn = <R extends { product_id: string }>(): Column<R> => ({
  key: "id", label: "Product ID", width: "130px", value: (row) => row.product_id,
});

export const productColumns = {
  name: { key: "name", label: "Product name", width: "minmax(140px, 1fr)", value: (row: ProductRow) => row.name } as Column<ProductRow>,
  brand: { key: "brand", label: "Brand name", width: "minmax(110px, 0.7fr)", value: (row: ProductRow) => row.brand } as Column<ProductRow>,
  location: { key: "location", label: "Location ID", width: "minmax(110px, 0.6fr)", value: (row: ProductRow) => row.location } as Column<ProductRow>,
  stock: { key: "stock", label: "Stock", width: "70px", align: "right", value: (row: ProductRow) => row.stock ?? "" } as Column<ProductRow>,
};

export const contentColumns: Column<ContentRow>[] = [
  idColumn<ContentRow>(),
  { key: "name", label: "Product name", width: "minmax(140px, 1fr)", value: (row) => row.name },
  { key: "stock", label: "Stock", width: "80px", align: "right", value: (row) => stockText(row.stock) },
  { key: "added", label: "Added to shelf", width: "170px", value: (row) => row.assigned_at || "Unknown" },
];
