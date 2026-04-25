import "./globals.css";

export const metadata = {
  title: "Trading Dashboard",
  description: "Live trading signals",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
