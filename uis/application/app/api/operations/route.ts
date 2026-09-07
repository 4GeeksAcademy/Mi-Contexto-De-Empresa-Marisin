import { NextRequest, NextResponse } from "next/server";
import { clientsData, inventoryData, returnsData, shipmentsData, ticketsData } from "@/lib/mockData";
import { filterCollection, groupCollectionBy, sortCollection } from "../../../../../src/utils/collections";
import { linearSearch } from "../../../../../src/utils/search";
import {
  generateCarrierPerformanceReport,
  generateCustomerExperienceReport,
  generateReturnAnalyticsReport,
  generateWarehouseStockReport,
} from "../../../../../src/utils/transformations";
import { checkClientHealthAndDeadlines, evaluatesHumanReviewNecessity, isStockLow } from "../../../../../src/utils/validations";

export async function GET(request: NextRequest) {
  const origin = request.nextUrl.searchParams.get("origin") as "Los Angeles" | "Zaragoza" | null;
  const tracking = request.nextUrl.searchParams.get("tracking")?.trim();

  const filteredShipments =
    origin && (origin === "Los Angeles" || origin === "Zaragoza")
      ? filterCollection(shipmentsData, { origin })
      : shipmentsData;

  const stockReport = generateWarehouseStockReport(inventoryData);
  const carrierReport = generateCarrierPerformanceReport(filteredShipments);
  const returnsReport = generateReturnAnalyticsReport(returnsData);
  const customerReport = generateCustomerExperienceReport(ticketsData);

  const lowStockSkus = inventoryData.filter((item) => isStockLow(item));
  const shipmentByCarrier = groupCollectionBy(filteredShipments, "carrierName");
  const expensiveShipments = sortCollection(filteredShipments, "costEuro", "desc").slice(0, 3);

  const trackingIndex = tracking ? linearSearch(shipmentsData, tracking, "trackingNumber") : -1;
  const trackingResult = trackingIndex >= 0 ? shipmentsData[trackingIndex] : null;

  const atRiskClients = clientsData
    .map((client) => ({ client, health: checkClientHealthAndDeadlines(client) }))
    .filter((entry) => entry.health.isHighRisk)
    .map((entry) => entry.client);

  const mandatoryHumanReview = returnsData.filter((orderReturn) => evaluatesHumanReviewNecessity(orderReturn)).length;

  return NextResponse.json({
    stockReport,
    carrierReport,
    returnsReport,
    customerReport,
    lowStockSkus,
    shipmentByCarrier,
    expensiveShipments,
    trackingResult,
    atRiskClients,
    mandatoryHumanReview,
  });
}
