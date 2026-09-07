import { NextResponse } from 'next/server';

export async function GET() {
  const csvRows = ['metric,value'];
  
  const csvContent = csvRows.join('\n');

  return new NextResponse(csvContent, {
    headers: {
      'Content-Type': 'text/csv',
      'Content-Disposition': 'attachment; filename="results.csv"',
    },
  });
}