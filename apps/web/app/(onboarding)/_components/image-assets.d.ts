declare module "*.png" {
  const asset: {
    src: string;
    width: number;
    height: number;
    blurDataURL?: string;
  };

  export default asset;
}

declare module "*.svg" {
  const asset: {
    src: string;
    width: number;
    height: number;
  };

  export default asset;
}
