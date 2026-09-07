import { BenefitsSection } from "@/components/BenefitsSection";
import { ContactFooter } from "@/components/ContactFooter";
import { CoverageSection } from "@/components/CoverageSection";
import { Header } from "@/components/Header";
import { Hero } from "@/components/Hero";
import { LeadForm } from "@/components/LeadForm";
import { ServicesSection } from "@/components/ServicesSection";

const organizationSchema = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "TrackFlow",
  url: "https://trackflow-logistics.com",
  logo: "https://trackflow-logistics.com/logo.png",
  description:
    "Operador logistico con hubs en Los Angeles y Zaragoza, especializado en fulfillment para e-commerce, ultima milla y logistica inversa.",
  foundingDate: "2009",
  areaServed: ["United States", "Spain"],
  numberOfEmployees: "130+",
  address: [
    {
      "@type": "PostalAddress",
      addressLocality: "Los Angeles",
      addressRegion: "CA",
      addressCountry: "US",
    },
    {
      "@type": "PostalAddress",
      addressLocality: "Zaragoza",
      addressRegion: "Aragon",
      addressCountry: "ES",
    },
  ],
  sameAs: ["https://www.linkedin.com/company/trackflow", "https://x.com/trackflow"],
  contactPoint: [
    {
      "@type": "ContactPoint",
      contactType: "sales",
      email: "sales.us@trackflow-logistics.com",
      telephone: "+13235550188",
      areaServed: "US",
    },
    {
      "@type": "ContactPoint",
      contactType: "sales",
      email: "sales.es@trackflow-logistics.com",
      telephone: "+34976555214",
      areaServed: "ES",
    },
  ],
};

export default function Home() {
  return (
    <main>
      <Header />
      <Hero />
      <ServicesSection />
      <CoverageSection />
      <BenefitsSection />
      <LeadForm />
      <ContactFooter />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationSchema) }}
      />
    </main>
  );
}
