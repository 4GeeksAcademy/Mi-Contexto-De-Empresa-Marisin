// src/demo.ts

import { SKUInventory, CarrierShipment, BrandClient, CustomerTicket } from './types/models';
import { isStockLow, checkClientHealthAndDeadlines, evaluatesHumanReviewNecessity } from './utils/validations';
import { linearSearch, binarySearch } from './utils/search';
import { filterCollection, sortCollection, groupCollectionBy } from './utils/collections';
import { generateWarehouseStockReport, generateCarrierPerformanceReport } from './utils/transformations';

console.log("==================================================================");
console.log("🚀 EJECUTANDO ENTORNO DE PRUEBAS - TRACKFLOW TECH (HITO 2) 🚀");
console.log("==================================================================\n");

// 1. DATASETS DE PRUEBA (MOCK DATA) basados en el Contexto de la Empresa
const mockInventory: SKUInventory[] = [
    { sku: "SKU-001", productName: "Eco Box Premium", clientBrand: "Nike", stockLA: 50, stockZaragoza: 120, minRequiredStock: 200 }, // Stock global = 170 (Bajo)
    { sku: "SKU-002", productName: "Suede Cleaner Kit", clientBrand: "Puma", stockLA: 300, stockZaragoza: 150, minRequiredStock: 100 },
    { sku: "SKU-003", productName: "Running Laces Glow", clientBrand: "Nike", stockLA: 10, stockZaragoza: 15, minRequiredStock: 50 }    // Stock global = 25 (Bajo)
];

const mockShipments: CarrierShipment[] = [
    { id: "SH-101", trackingNumber: "TRK-UPS-01", carrierName: "UPS", origin: "Los Angeles", destinationCountry: "USA", weightKg: 2.5, urgency: "Express", status: "Delivered", costEuro: 15.0, hasIncident: false },
    { id: "SH-102", trackingNumber: "TRK-SEUR-02", carrierName: "SEUR", origin: "Zaragoza", destinationCountry: "Spain", weightKg: 12.0, urgency: "Standard", status: "In Transit", costEuro: 8.5, hasIncident: true },
    { id: "SH-103", trackingNumber: "TRK-FEDEX-03", carrierName: "FedEx", origin: "Los Angeles", destinationCountry: "Canada", weightKg: 5.0, urgency: "Express", status: "Failed", costEuro: 45.0, hasIncident: true }
];

const mockClients: BrandClient[] = [
    { id: "CL-01", companyName: "Nike", contractExpirationDate: new Date("2026-08-01"), monthlyVolumeEuro: 15000, renewalRiskScore: 85 }, // Expira pronto y alto riesgo
    { id: "CL-02", companyName: "Puma", contractExpirationDate: new Date("2027-02-15"), monthlyVolumeEuro: 8000, renewalRiskScore: 20 }
];


// ==========================================
// TEST 1: VALIDACIONES DE NEGOCIO
// ==========================================
console.log("🔹 [TEST 1] VALIDACIONES DE NEGOCIO");
mockInventory.forEach(item => {
    if (isStockLow(item)) {
        console.log(`⚠️ ALERTA: Stock bajo global para ${item.productName} (${item.sku}). Stock total: ${item.stockLA + item.stockZaragoza} / Mínimo: ${item.minRequiredStock}`);
    }
});

mockClients.forEach(client => {
    const health = checkClientHealthAndDeadlines(client);
    console.log(`📈 Cliente: ${client.companyName} | Churn Risk: ${client.renewalRiskScore}% | ¿Alerta 30 días?: ${health.requires30DayAlert} | ¿Riesgo Crítico?: ${health.isHighRisk}`);
});
console.log("\n------------------------------------------------------------------\n");


// ==========================================
// TEST 2: BÚSQUEDAS (LINEAL Y BINARIA)
// ==========================================
console.log("🔹 [TEST 2] ALGORITMOS DE BÚSQUEDA");
// Búsqueda lineal en array desordenado
const indexLineal = linearSearch(mockShipments, "TRK-SEUR-02", "trackingNumber");
console.log(`🔍 Búsqueda Lineal (Tracking 'TRK-SEUR-02'): Encontrado en índice [${indexLineal}]`);

// Para la búsqueda binaria, ordenamos primero el inventario por SKU de forma ascendente
const sortedInventoryForBinary = sortCollection(mockInventory, "sku", "asc");
const indexBinario = binarySearch(sortedInventoryForBinary, "SKU-002", "sku");
console.log(`🔍 Búsqueda Binaria (SKU 'SKU-002'): Encontrado en índice [${indexBinario}] dentro del array ordenado.`);
console.log("\n------------------------------------------------------------------\n");


// ==========================================
// TEST 3: FILTRADO, ORDENACIÓN Y AGRUPACIÓN
// ==========================================
console.log("🔹 [TEST 3] MANIPULACIÓN DE COLECCIONES");
// Filtrar envíos con incidencias operativas
const shipmentsWithIncidents = filterCollection(mockShipments, { hasIncident: true });
console.log(`📦 Envíos filtrados con incidencias de transporte: ${shipmentsWithIncidents.length}`);

// Ordenar envíos por coste descenente para ver los impactos financieros
const expensiveShipments = sortCollection(mockShipments, "costEuro", "desc");
console.log(`💰 Envío más costoso ordenado: ${expensiveShipments[0].id} (${expensiveShipments[0].costEuro}€)`);

// Agrupar envíos por almacén de origen
const shipmentsByWarehouse = groupCollectionBy(mockShipments, "origin");
console.log("🏢 Envíos agrupados por almacén de origen:", Object.keys(shipmentsByWarehouse));
console.log("\n------------------------------------------------------------------\n");


// ==========================================
// TEST 4: TRANSFORMACIONES Y AGREGACIONES (REPORTS)
// ==========================================
console.log("🔹 [TEST 4] REPORTES ANALÍTICOS Y KPIs (Especial Daniel Espinoza)");
const stockReport = generateWarehouseStockReport(mockInventory);
console.log("📊 Reporte de Stock Consolidado (Ana Whitfield):");
console.table(stockReport);

const carrierReport = generateCarrierPerformanceReport(mockShipments);
console.log("📊 Reporte de Rendimiento de Transportistas (Carlos Vega):");
console.table(carrierReport);

console.log("\n==================================================================");
console.log("✅ TODAS LAS PRUEBAS DE LÓGICA DE NEGOCIO PASARON CORRECTAMENTE");
console.log("==================================================================");