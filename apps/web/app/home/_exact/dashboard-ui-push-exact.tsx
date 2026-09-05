import type { ReactNode } from "react";

import styles from "../home.module.css";

type DashboardUiPushExactProps = {
    brand?: ReactNode;
    createControl?: ReactNode;
    allies?: ReactNode;
    profile?: ReactNode;
    thread?: ReactNode;
};

export function DashboardUiPushExact({
    brand,
    createControl,
    allies,
    profile,
    thread,
}: DashboardUiPushExactProps) {
    return (
        <div
            style={{
                backgroundColor: "#fff",
                overflow: "hidden",
                width: "100%",
                height: "100%",
                position: "relative",
            }}
        >
            <div
                style={{
                    borderWidth: "0px 1px 0px 0px",
                    borderStyle: "solid",
                    borderColor: "#e8e8e8",
                    backgroundColor: "#fff",
                    overflow: "hidden",
                    top: 0,
                    left: 0,
                    bottom: 0,
                    width: 432,
                    height: "100%",
                    position: "absolute",
                }}
            >
                <div
                    style={{
                        borderRadius: 100,
                        backgroundColor: "#f0f0f0",
                        overflow: "hidden",
                        left: 36,
                        top: 102,
                        width: 360,
                        height: 48,
                        position: "absolute",
                    }}
                >
                    <div
                        style={{
                            display: "flex",
                            flexDirection: "row",
                            gridColumnGap: 8,
                            alignItems: "center",
                            justifyContent: "flex-start",
                            left: 18,
                            top: "calc(-12px + 50%)",
                            width: "min-content",
                            position: "absolute",
                        }}
                    >
                        <div
                            style={{
                                overflow: "hidden",
                                width: 24,
                                height: 24,
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            <img
                                data-figma-node-id="384:8391"
                                data-figma-asset="Group"
                                src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788574629/figma-screens/batch_mtnr5g8w_npmoz/dashboard-ui-push/assets/group.svg"
                                alt="Group"
                                width={19}
                                height={19}
                                style={{
                                    left: "10.4%",
                                    top: "10.4%",
                                    right: "10.4%",
                                    bottom: "10.4%",
                                    width: "79.2%",
                                    height: "79.2%",
                                    position: "absolute",
                                }}
                            />
                        </div>
                        <span
                            className="text"
                            style={{
                                display: "inline",
                                textAlign: "left",
                                fontSize: 16,
                                fontFamily:
                                    '"Open Runde", Inter, system-ui, sans-serif',
                                fontWeight: 600,
                                fontStretch: "100%",
                                letterSpacing: "-0.58px",
                                color: "#757575",
                                width: "max-content",
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            Search
                        </span>
                    </div>
                </div>
                <div
                    style={{
                        display: "flex",
                        flexDirection: "row",
                        gridColumnGap: 12,
                        alignItems: "center",
                        justifyContent: "flex-start",
                        left: 36,
                        top: 178,
                        width: "min-content",
                        height: 33,
                        position: "absolute",
                    }}
                >
                    <div
                        style={{
                            borderRadius: 100,
                            backgroundColor: "#ff5800",
                            display: "flex",
                            flexDirection: "row",
                            gridColumnGap: 10,
                            alignItems: "center",
                            justifyContent: "center",
                            width: "min-content",
                            height: 33,
                            position: "relative",
                            flexShrink: 0,
                            padding: "0 12px",
                        }}
                    >
                        <span
                            className="text"
                            style={{
                                display: "inline",
                                textAlign: "left",
                                fontSize: 14,
                                fontFamily:
                                    '"Open Runde", Inter, system-ui, sans-serif',
                                fontWeight: 600,
                                fontStretch: "100%",
                                letterSpacing: "-0.62px",
                                lineHeight: "100%",
                                color: "#fff",
                                width: "max-content",
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            My allies
                        </span>
                    </div>
                    <div
                        style={{
                            borderRadius: 100,
                            backgroundColor: "#f3f3f3",
                            display: "flex",
                            flexDirection: "row",
                            gridColumnGap: 10,
                            alignItems: "center",
                            justifyContent: "center",
                            width: "min-content",
                            height: 33,
                            position: "relative",
                            flexShrink: 0,
                            padding: "0 12px",
                        }}
                    >
                        <span
                            className="text"
                            style={{
                                display: "inline",
                                textAlign: "left",
                                fontSize: 14,
                                fontFamily:
                                    '"Open Runde", Inter, system-ui, sans-serif',
                                fontWeight: 600,
                                fontStretch: "100%",
                                letterSpacing: "-0.61px",
                                lineHeight: "100%",
                                color: "#757575",
                                width: "max-content",
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            Routines
                        </span>
                    </div>
                </div>
                {allies ? (
                    <div
                        style={{
                            left: 36,
                            top: 235,
                            right: 36,
                            bottom: 104,
                            position: "absolute",
                            overflowY: "auto",
                        }}
                    >
                        {allies}
                    </div>
                ) : (
                    <>
                        <div
                            style={{
                                display: "flex",
                                flexDirection: "row",
                                gridColumnGap: 12,
                                alignItems: "center",
                                justifyContent: "flex-start",
                                left: 36,
                                top: 235,
                                width: "min-content",
                                position: "absolute",
                            }}
                        >
                            <div
                                style={{
                                    overflow: "hidden",
                                    width: "49.3px",
                                    height: 48,
                                    position: "relative",
                                    flexShrink: 0,
                                }}
                            >
                                <div
                                    style={{
                                        borderRadius: 32,
                                        backgroundColor: "#3446e9",
                                        overflow: "hidden",
                                        left: 0,
                                        top: 0,
                                        width: "49.3px",
                                        height: 48,
                                        position: "absolute",
                                    }}
                                >
                                    <div
                                        style={{
                                            overflow: "hidden",
                                            left: "calc(-15px + 50%)",
                                            top: "calc(-16.5px + 50%)",
                                            width: "30.2px",
                                            height: 33,
                                            position: "absolute",
                                        }}
                                    >
                                        <img
                                            data-figma-node-id="384:7834"
                                            data-figma-asset="fill"
                                            src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788574630/figma-screens/batch_mtnr5g8w_npmoz/dashboard-ui-push/assets/fill.svg"
                                            alt="fill"
                                            width={30}
                                            height={33}
                                            style={{
                                                left: "-3.7%",
                                                top: "-3.4%",
                                                right: "-3.2%",
                                                bottom: "-3%",
                                                width: "106.9%",
                                                height: "106.4%",
                                                position: "absolute",
                                            }}
                                        />
                                        <div
                                            style={{
                                                overflow: "hidden",
                                                left: "calc(-11px + 50%)",
                                                top: "7.6px",
                                                width: "12.7px",
                                                height: "8.9px",
                                                position: "absolute",
                                            }}
                                        >
                                            <div
                                                style={{
                                                    overflow: "hidden",
                                                    left: 0,
                                                    top: 0,
                                                    width: "4.8px",
                                                    height: "8.9px",
                                                    position: "absolute",
                                                }}
                                            >
                                                <svg
                                                    width="4.747260093688966"
                                                    height="8.912921905517578"
                                                    viewBox="0 0 4.747260093688966 8.912921905517578"
                                                    fill="none"
                                                    xmlns="http://www.w3.org/2000/svg"
                                                    xmlnsXlink="http://www.w3.org/1999/xlink"
                                                    preserveAspectRatio="none"
                                                    style={{
                                                        left: "0.1%",
                                                        top: 0,
                                                        right: 0,
                                                        bottom: 0,
                                                        width: "99.9%",
                                                        height: "100%",
                                                        position: "absolute",
                                                    }}
                                                >
                                                    <path
                                                        d="M2.3736 0C3.6846 0 4.7473 1.9955 4.7473 4.4565 4.7473 6.9174 3.6846 8.9129 2.3736 8.9129 1.0626 8.9129 0 6.9174 0 4.4565 0 1.9955 1.0626 0 2.3736 0Z"
                                                        style={{
                                                            fillRule: "nonzero",
                                                            fill: "#000",
                                                        }}
                                                    />
                                                </svg>
                                                <div
                                                    style={{
                                                        overflow: "hidden",
                                                        left: 0,
                                                        top: "0.1%",
                                                        right: "0.1%",
                                                        bottom: "0.1%",
                                                        width: "99.9%",
                                                        height: "99.9%",
                                                        position: "absolute",
                                                    }}
                                                >
                                                    <div
                                                        style={{
                                                            overflow: "hidden",
                                                            left: "-23.7%",
                                                            top: "29.1%",
                                                            right: "53%",
                                                            bottom: "28.5%",
                                                            width: "70.7%",
                                                            height: "42.3%",
                                                            position:
                                                                "absolute",
                                                            maskImage:
                                                                'url("data:image/svg+xml',
                                                            maskRepeat:
                                                                "no-repeat",
                                                            maskType:
                                                                "luminance",
                                                            maskPosition:
                                                                "1.1px -2.6px",
                                                        }}
                                                    >
                                                        <svg
                                                            width="3.7696335315704346"
                                                            height="3.35665"
                                                            viewBox="0 0 3.7696335315704346 3.35665"
                                                            fill="none"
                                                            xmlns="http://www.w3.org/2000/svg"
                                                            xmlnsXlink="http://www.w3.org/1999/xlink"
                                                            preserveAspectRatio="none"
                                                            style={{
                                                                transformOrigin:
                                                                    "0 0",
                                                                transform:
                                                                    "rotate(90deg)",
                                                                left: "100%",
                                                                top: 0,
                                                                right: "-112.3%",
                                                                bottom: "11%",
                                                                width: "112.3%",
                                                                height: "89%",
                                                                position:
                                                                    "absolute",
                                                            }}
                                                        >
                                                            <path
                                                                d="M2.0314 0.261l1.5976 2.8453c0.0629 0.112-0.0181 0.2504-0.1465 0.2504h-3.1953c-0.1285 0-0.2095-0.1384-0.1466-0.2504l1.5976-2.8453c0.0642-0.1144 0.2289-0.1144 0.2932 0z"
                                                                style={{
                                                                    fillRule:
                                                                        "nonzero",
                                                                    fill: "#fff",
                                                                }}
                                                            />
                                                        </svg>
                                                    </div>
                                                </div>
                                            </div>
                                            <div
                                                style={{
                                                    overflow: "hidden",
                                                    left: "7.9px",
                                                    top: 0,
                                                    width: "4.7px",
                                                    height: "8.9px",
                                                    position: "absolute",
                                                }}
                                            >
                                                <svg
                                                    width="4.747260093688966"
                                                    height="8.912921905517578"
                                                    viewBox="0 0 4.747260093688966 8.912921905517578"
                                                    fill="none"
                                                    xmlns="http://www.w3.org/2000/svg"
                                                    xmlnsXlink="http://www.w3.org/1999/xlink"
                                                    preserveAspectRatio="none"
                                                    style={{
                                                        left: 0,
                                                        top: 0,
                                                        right: 0,
                                                        bottom: 0,
                                                        width: "100%",
                                                        height: "100%",
                                                        position: "absolute",
                                                    }}
                                                >
                                                    <path
                                                        d="M2.3736 0C3.6846 0 4.7473 1.9955 4.7473 4.4565 4.7473 6.9174 3.6846 8.9129 2.3736 8.9129 1.0626 8.9129 0 6.9174 0 4.4565 0 1.9955 1.0626 0 2.3736 0Z"
                                                        style={{
                                                            fillRule: "nonzero",
                                                            fill: "#000",
                                                        }}
                                                    />
                                                </svg>
                                                <div
                                                    style={{
                                                        overflow: "hidden",
                                                        left: 0,
                                                        top: "0.1%",
                                                        right: 0,
                                                        bottom: "0.1%",
                                                        width: "100%",
                                                        height: "99.9%",
                                                        position: "absolute",
                                                    }}
                                                >
                                                    <div
                                                        style={{
                                                            overflow: "hidden",
                                                            left: "-23.7%",
                                                            top: "29.1%",
                                                            right: "53%",
                                                            bottom: "28.5%",
                                                            width: "70.7%",
                                                            height: "42.3%",
                                                            position:
                                                                "absolute",
                                                            maskImage:
                                                                'url("data:image/svg+xml',
                                                            maskRepeat:
                                                                "no-repeat",
                                                            maskType:
                                                                "luminance",
                                                            maskPosition:
                                                                "1.1px -2.6px",
                                                        }}
                                                    >
                                                        <svg
                                                            width="3.7696335315704346"
                                                            height="3.35665"
                                                            viewBox="0 0 3.7696335315704346 3.35665"
                                                            fill="none"
                                                            xmlns="http://www.w3.org/2000/svg"
                                                            xmlnsXlink="http://www.w3.org/1999/xlink"
                                                            preserveAspectRatio="none"
                                                            style={{
                                                                transformOrigin:
                                                                    "0 0",
                                                                transform:
                                                                    "rotate(90deg)",
                                                                left: "100%",
                                                                top: 0,
                                                                right: "-112.3%",
                                                                bottom: "11%",
                                                                width: "112.3%",
                                                                height: "89%",
                                                                position:
                                                                    "absolute",
                                                            }}
                                                        >
                                                            <path
                                                                d="M2.0314 0.261l1.5976 2.8453c0.0629 0.112-0.0181 0.2504-0.1465 0.2504h-3.1953c-0.1285 0-0.2095-0.1384-0.1466-0.2504l1.5976-2.8453c0.0642-0.1144 0.2289-0.1144 0.2932 0z"
                                                                style={{
                                                                    fillRule:
                                                                        "nonzero",
                                                                    fill: "#fff",
                                                                }}
                                                            />
                                                        </svg>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div
                                    style={{
                                        borderWidth: 1,
                                        borderStyle: "solid",
                                        borderColor: "#fff",
                                        borderRadius: "50%",
                                        backgroundColor: "#12c25b",
                                        left: 37,
                                        top: 35,
                                        aspectRatio: 1,
                                        width: "auto",
                                        height: 10,
                                        position: "absolute",
                                    }}
                                ></div>
                            </div>
                            <div
                                style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    rowGap: 6,
                                    alignItems: "start",
                                    justifyContent: "flex-start",
                                    width: "min-content",
                                    position: "relative",
                                    flexShrink: 0,
                                }}
                            >
                                <span
                                    className="text"
                                    style={{
                                        display: "inline",
                                        textAlign: "left",
                                        fontSize: 18,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 600,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.75px",
                                        lineHeight: "100%",
                                        color: "#121212",
                                        width: "max-content",
                                        position: "relative",
                                        flexShrink: 0,
                                    }}
                                >
                                    timi
                                </span>
                                <span
                                    className="text"
                                    style={{
                                        display: "block",
                                        textAlign: "left",
                                        fontSize: 14,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 500,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.48px",
                                        lineHeight: "100%",
                                        color: "#757575",
                                        width: 299,
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        whiteSpace: "nowrap",
                                        position: "relative",
                                        flexShrink: 0,
                                    }}
                                >
                                    Think of me as your always-available partner
                                    for brainstorming,
                                </span>
                            </div>
                        </div>
                        <span
                            className="text"
                            style={{
                                display: "inline",
                                textAlign: "right",
                                fontSize: 12,
                                fontFamily:
                                    '"Open Runde", Inter, system-ui, sans-serif',
                                fontWeight: 500,
                                fontStretch: "100%",
                                letterSpacing: "-0.44px",
                                color: "#a0a0a0",
                                top: 237,
                                right: 36,
                                width: "max-content",
                                position: "absolute",
                            }}
                        >
                            12:20 PM
                        </span>
                        <div
                            style={{
                                display: "flex",
                                flexDirection: "row",
                                gridColumnGap: 12,
                                alignItems: "center",
                                justifyContent: "flex-start",
                                left: 36,
                                top: 307,
                                width: "min-content",
                                position: "absolute",
                            }}
                        >
                            <div
                                style={{
                                    overflow: "hidden",
                                    width: "49.3px",
                                    height: 48,
                                    position: "relative",
                                    flexShrink: 0,
                                }}
                            >
                                <div
                                    style={{
                                        borderRadius: 32,
                                        backgroundColor: "#fd304f",
                                        overflow: "hidden",
                                        left: 0,
                                        top: 0,
                                        width: "49.3px",
                                        height: 48,
                                        position: "absolute",
                                    }}
                                >
                                    <img
                                        data-figma-node-id="384:7859"
                                        data-figma-asset="Vector"
                                        src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788574633/figma-screens/batch_mtnr5g8w_npmoz/dashboard-ui-push/assets/vector.svg"
                                        alt="Vector"
                                        width={33}
                                        height={32}
                                        style={{
                                            left: "13.6%",
                                            top: "13.5%",
                                            right: "13.9%",
                                            bottom: "13.9%",
                                            width: "72.5%",
                                            height: "72.7%",
                                            position: "absolute",
                                        }}
                                    />
                                    <div
                                        style={{
                                            overflow: "hidden",
                                            left: "20.9px",
                                            top: "15.6px",
                                            width: "14.7px",
                                            height: "8.4px",
                                            position: "absolute",
                                        }}
                                    >
                                        <div
                                            style={{
                                                overflow: "hidden",
                                                left: 0,
                                                top: 0,
                                                width: "4.9px",
                                                height: "8.4px",
                                                position: "absolute",
                                            }}
                                        >
                                            <svg
                                                width="4.87788724899292"
                                                height="8.399999618530273"
                                                viewBox="0 0 4.87788724899292 8.399999618530273"
                                                fill="none"
                                                xmlns="http://www.w3.org/2000/svg"
                                                xmlnsXlink="http://www.w3.org/1999/xlink"
                                                preserveAspectRatio="none"
                                                style={{
                                                    left: "0.1%",
                                                    top: 0,
                                                    right: 0,
                                                    bottom: 0,
                                                    width: "99.9%",
                                                    height: "100%",
                                                    position: "absolute",
                                                }}
                                            >
                                                <path
                                                    d="M2.4389 0C3.786 0 4.8779 1.8806 4.8779 4.2 4.8779 6.5194 3.786 8.4 2.4389 8.4 1.0919 8.4 0 6.5194 0 4.2 0 1.8806 1.0919 0 2.4389 0Z"
                                                    style={{
                                                        fillRule: "nonzero",
                                                        fill: "#000",
                                                    }}
                                                />
                                            </svg>
                                            <div
                                                style={{
                                                    overflow: "hidden",
                                                    left: 0,
                                                    top: "0.1%",
                                                    right: "0.1%",
                                                    bottom: "0.1%",
                                                    width: "99.9%",
                                                    height: "99.9%",
                                                    position: "absolute",
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        overflow: "hidden",
                                                        left: "-23.7%",
                                                        top: "29.1%",
                                                        right: "53%",
                                                        bottom: "28.5%",
                                                        width: "70.7%",
                                                        height: "42.3%",
                                                        position: "absolute",
                                                        maskImage:
                                                            'url("data:image/svg+xml',
                                                        maskRepeat: "no-repeat",
                                                        maskType: "luminance",
                                                        maskPosition:
                                                            "1.2px -2.4px",
                                                    }}
                                                >
                                                    <svg
                                                        width="3.5526986122131348"
                                                        height="3.449011325836182"
                                                        viewBox="0 0 3.5526986122131348 3.449011325836182"
                                                        fill="none"
                                                        xmlns="http://www.w3.org/2000/svg"
                                                        xmlnsXlink="http://www.w3.org/1999/xlink"
                                                        preserveAspectRatio="none"
                                                        style={{
                                                            transformOrigin:
                                                                "0 0",
                                                            transform:
                                                                "rotate(90deg)",
                                                            left: "100%",
                                                            top: 0,
                                                            right: "-103%",
                                                            bottom: "2.9%",
                                                            width: "103%",
                                                            height: "97.1%",
                                                            position:
                                                                "absolute",
                                                        }}
                                                    >
                                                        <path
                                                            d="M1.7763 0L3.5527 3.449H0L1.7763 0Z"
                                                            style={{
                                                                fillRule:
                                                                    "nonzero",
                                                                fill: "#fff",
                                                            }}
                                                        />
                                                    </svg>
                                                </div>
                                            </div>
                                        </div>
                                        <div
                                            style={{
                                                overflow: "hidden",
                                                left: "9.9px",
                                                top: 0,
                                                width: "4.9px",
                                                height: "8.4px",
                                                position: "absolute",
                                            }}
                                        >
                                            <svg
                                                width="4.87788724899292"
                                                height="8.399999618530273"
                                                viewBox="0 0 4.87788724899292 8.399999618530273"
                                                fill="none"
                                                xmlns="http://www.w3.org/2000/svg"
                                                xmlnsXlink="http://www.w3.org/1999/xlink"
                                                preserveAspectRatio="none"
                                                style={{
                                                    left: "0.1%",
                                                    top: 0,
                                                    right: 0,
                                                    bottom: 0,
                                                    width: "99.9%",
                                                    height: "100%",
                                                    position: "absolute",
                                                }}
                                            >
                                                <path
                                                    d="M2.4389 0C3.786 0 4.8779 1.8806 4.8779 4.2 4.8779 6.5194 3.786 8.4 2.4389 8.4 1.0919 8.4 0 6.5194 0 4.2 0 1.8806 1.0919 0 2.4389 0Z"
                                                    style={{
                                                        fillRule: "nonzero",
                                                        fill: "#000",
                                                    }}
                                                />
                                            </svg>
                                            <div
                                                style={{
                                                    overflow: "hidden",
                                                    left: 0,
                                                    top: "0.1%",
                                                    right: "0.1%",
                                                    bottom: "0.1%",
                                                    width: "99.9%",
                                                    height: "99.9%",
                                                    position: "absolute",
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        overflow: "hidden",
                                                        left: "-23.7%",
                                                        top: "29.1%",
                                                        right: "53%",
                                                        bottom: "28.5%",
                                                        width: "70.7%",
                                                        height: "42.3%",
                                                        position: "absolute",
                                                        maskImage:
                                                            'url("data:image/svg+xml',
                                                        maskRepeat: "no-repeat",
                                                        maskType: "luminance",
                                                        maskPosition:
                                                            "1.2px -2.4px",
                                                    }}
                                                >
                                                    <svg
                                                        width="3.5526986122131348"
                                                        height="3.449011325836182"
                                                        viewBox="0 0 3.5526986122131348 3.449011325836182"
                                                        fill="none"
                                                        xmlns="http://www.w3.org/2000/svg"
                                                        xmlnsXlink="http://www.w3.org/1999/xlink"
                                                        preserveAspectRatio="none"
                                                        style={{
                                                            transformOrigin:
                                                                "0 0",
                                                            transform:
                                                                "rotate(90deg)",
                                                            left: "100%",
                                                            top: 0,
                                                            right: "-103%",
                                                            bottom: "2.9%",
                                                            width: "103%",
                                                            height: "97.1%",
                                                            position:
                                                                "absolute",
                                                        }}
                                                    >
                                                        <path
                                                            d="M1.7763 0L3.5527 3.449H0L1.7763 0Z"
                                                            style={{
                                                                fillRule:
                                                                    "nonzero",
                                                                fill: "#fff",
                                                            }}
                                                        />
                                                    </svg>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div
                                    style={{
                                        borderWidth: 1,
                                        borderStyle: "solid",
                                        borderColor: "#fff",
                                        borderRadius: "50%",
                                        backgroundColor: "#12c25b",
                                        left: 37,
                                        top: 35,
                                        aspectRatio: 1,
                                        width: "auto",
                                        height: 10,
                                        position: "absolute",
                                    }}
                                ></div>
                            </div>
                            <div
                                style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    rowGap: 6,
                                    alignItems: "start",
                                    justifyContent: "flex-start",
                                    width: "min-content",
                                    position: "relative",
                                    flexShrink: 0,
                                }}
                            >
                                <span
                                    className="text"
                                    style={{
                                        display: "inline",
                                        textAlign: "left",
                                        fontSize: 18,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 600,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.80px",
                                        lineHeight: "100%",
                                        color: "#121212",
                                        width: "max-content",
                                        position: "relative",
                                        flexShrink: 0,
                                    }}
                                >
                                    Sally
                                </span>
                                <span
                                    className="text"
                                    style={{
                                        display: "block",
                                        textAlign: "left",
                                        fontSize: 14,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 500,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.48px",
                                        lineHeight: "100%",
                                        color: "#757575",
                                        width: 299,
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        whiteSpace: "nowrap",
                                        position: "relative",
                                        flexShrink: 0,
                                    }}
                                >
                                    Welcome! I am your ally, and I am thrilled
                                    to announce
                                </span>
                            </div>
                        </div>
                        <span
                            className="text"
                            style={{
                                display: "inline",
                                textAlign: "right",
                                fontSize: 12,
                                fontFamily:
                                    '"Open Runde", Inter, system-ui, sans-serif',
                                fontWeight: 500,
                                fontStretch: "100%",
                                letterSpacing: "-0.43px",
                                color: "#a0a0a0",
                                left: 350,
                                top: 309,
                                width: "max-content",
                                position: "absolute",
                            }}
                        >
                            9:40 AM
                        </span>
                    </>
                )}
                {createControl ? (
                    <div
                        style={{
                            left: "calc(132px + 50%)",
                            top: 36,
                            position: "absolute",
                        }}
                    >
                        {createControl}
                    </div>
                ) : (
                    <div
                        style={{
                            borderRadius: "75.8px",
                            backgroundColor: "#ff5800",
                            display: "flex",
                            flexDirection: "row",
                            gridColumnGap: "12.6px",
                            alignItems: "center",
                            justifyContent: "center",
                            left: "calc(132px + 50%)",
                            top: 36,
                            width: "min-content",
                            position: "absolute",
                            padding: "12.6px",
                        }}
                    >
                        <div
                            style={{
                                overflow: "hidden",
                                width: "22.7px",
                                height: "22.7px",
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            <img
                                data-figma-node-id="384:8386"
                                data-figma-asset="Group"
                                src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788574636/figma-screens/batch_mtnr5g8w_npmoz/dashboard-ui-push/assets/group-2.svg"
                                alt="Group"
                                width={16}
                                height={16}
                                style={{
                                    left: "13.9%",
                                    top: "13.9%",
                                    right: "13.9%",
                                    bottom: "13.9%",
                                    width: "72.2%",
                                    height: "72.2%",
                                    position: "absolute",
                                }}
                            />
                        </div>
                    </div>
                )}
                {profile ? (
                    <div style={{ left: 36, bottom: 48, position: "absolute" }}>
                        {profile}
                    </div>
                ) : (
                    <div
                        style={{
                            display: "flex",
                            flexDirection: "row",
                            gridColumnGap: 12,
                            alignItems: "center",
                            justifyContent: "flex-start",
                            left: 36,
                            bottom: 48,
                            width: "min-content",
                            position: "absolute",
                        }}
                    >
                        <div
                            style={{
                                borderRadius: "50%",
                                backgroundColor: "#f0f0f0",
                                overflow: "hidden",
                                width: 40,
                                height: 40,
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            <span
                                className="text"
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    inset: 0,
                                    textAlign: "center",
                                    fontSize: 20,
                                    fontFamily:
                                        '"Open Runde", Inter, system-ui, sans-serif',
                                    fontWeight: 600,
                                    fontStretch: "100%",
                                    letterSpacing: "-0.50px",
                                    lineHeight: 1,
                                    color: "#000",
                                    position: "absolute",
                                }}
                            >
                                SD
                            </span>
                        </div>
                        <span
                            className="text"
                            style={{
                                display: "inline",
                                textAlign: "left",
                                fontSize: 18,
                                fontFamily:
                                    '"Open Runde", Inter, system-ui, sans-serif',
                                fontWeight: 600,
                                fontStretch: "100%",
                                letterSpacing: "-0.91px",
                                color: "#121212",
                                width: "max-content",
                                position: "relative",
                                flexShrink: 0,
                            }}
                        >
                            Sam Dickson
                        </span>
                    </div>
                )}
                <div
                    style={{
                        overflow: "hidden",
                        left: 36,
                        top: 36,
                        width: 48,
                        height: 48,
                        position: "absolute",
                    }}
                >
                    {brand ?? (
                        <img
                            src="/allies-icon.svg"
                            alt="Allies"
                            width={48}
                            height={48}
                            style={{ width: 48, height: 48, display: "block" }}
                        />
                    )}
                </div>
            </div>
            {thread ? (
                <div
                    style={{
                        backgroundColor: "#fff",
                        overflow: "hidden",
                        top: 0,
                        left: 432,
                        right: 0,
                        bottom: 0,
                        position: "absolute",
                    }}
                >
                    {thread}
                </div>
            ) : (
                <div
                    style={{
                        backgroundColor: "#fff",
                        overflow: "hidden",
                        top: 0,
                        left: 432,
                        right: 0,
                        bottom: 0,
                        position: "absolute",
                    }}
                >
                    <div
                        style={{
                            borderWidth: "0px 0px 1px",
                            borderStyle: "solid",
                            borderColor: "#e8e8e8",
                            backgroundColor: "#fff",
                            overflow: "hidden",
                            top: 0,
                            left: 0,
                            right: 0,
                            height: 52,
                            position: "absolute",
                        }}
                    >
                        <div
                            style={{
                                display: "flex",
                                flexDirection: "row",
                                gridColumnGap: 8,
                                alignItems: "center",
                                justifyContent: "flex-start",
                                left: "calc(-63px + 50%)",
                                top: "calc(-12px + 50%)",
                                width: "min-content",
                                position: "absolute",
                            }}
                        >
                            <div
                                style={{
                                    overflow: "hidden",
                                    width: 24,
                                    height: 24,
                                    position: "relative",
                                    flexShrink: 0,
                                }}
                            >
                                <img
                                    data-figma-node-id="384:8710"
                                    data-figma-asset="Group"
                                    src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788574656/figma-screens/batch_mtnr5g8w_npmoz/dashboard-ui-push/assets/group-3.svg"
                                    alt="Group"
                                    width={21}
                                    height={21}
                                    style={{
                                        left: "5.6%",
                                        top: "5.6%",
                                        right: "5.5%",
                                        bottom: "5.5%",
                                        width: "88.9%",
                                        height: "88.9%",
                                        position: "absolute",
                                    }}
                                />
                            </div>
                            <span
                                className="text"
                                style={{
                                    display: "inline",
                                    textAlign: "left",
                                    fontSize: 16,
                                    fontFamily:
                                        '"Open Runde", Inter, system-ui, sans-serif',
                                    fontWeight: 500,
                                    fontStretch: "100%",
                                    letterSpacing: "-0.65px",
                                    color: "#757575",
                                    width: "max-content",
                                    position: "relative",
                                    flexShrink: 0,
                                }}
                            >
                                Sally settings
                            </span>
                        </div>
                    </div>
                    <label
                        style={{
                            borderRadius: 100,
                            backgroundColor: "#f3f3f3",
                            overflow: "hidden",
                            left: "calc(50% - 300px)",
                            bottom: 48,
                            width: 600,
                            height: 60,
                            position: "absolute",
                            cursor: "text",
                        }}
                    >
                        <input
                            className={styles.exactComposerInput}
                            type="text"
                            name="reply"
                            placeholder="Reply Sally"
                            aria-label="Reply Sally"
                            autoComplete="off"
                            style={{
                                left: 48,
                                right: 61,
                                top: 0,
                                bottom: 0,
                                width: "auto",
                                height: 60,
                                position: "absolute",
                            }}
                        />
                        <div
                            style={{
                                borderRadius: 24,
                                backgroundColor: "#d9d9d9",
                                overflow: "hidden",
                                top: "calc(-18px + 50%)",
                                right: 12,
                                width: 37,
                                height: 36,
                                position: "absolute",
                            }}
                        >
                            <div
                                style={{
                                    overflow: "hidden",
                                    left: "calc(-8.5px + 50%)",
                                    top: "calc(-9px + 50%)",
                                    width: 18,
                                    height: 18,
                                    position: "absolute",
                                }}
                            >
                                <svg
                                    width={14}
                                    height={18}
                                    viewBox="0 0 14 18"
                                    fill="none"
                                    xmlns="http://www.w3.org/2000/svg"
                                    xmlnsXlink="http://www.w3.org/1999/xlink"
                                    preserveAspectRatio="none"
                                    style={{
                                        left: "11.1%",
                                        top: 0,
                                        right: "11.1%",
                                        bottom: 0,
                                        width: "77.8%",
                                        height: "100%",
                                        position: "absolute",
                                    }}
                                >
                                    <defs>
                                        <clipPath id="def_0_5">
                                            <rect
                                                x={0}
                                                y={0}
                                                width={14}
                                                height={18}
                                            ></rect>
                                        </clipPath>
                                    </defs>
                                    <g style={{ clipPath: "url(#def_0_5)" }}>
                                        <path
                                            d="M3 4C3 1.7909 4.7908 0 7 0 9.2092 0 11 1.7909 11 4V7.5C11 9.7091 9.2092 11.5 7 11.5 4.7908 11.5 3 9.7091 3 7.5V4Z"
                                            style={{
                                                fillRule: "evenodd",
                                                fill: "rgba(117,117,117,0.4)",
                                            }}
                                        />
                                        <path
                                            d="M11 5.0001V6.5001H7.75C7.3358 6.5001 7 6.1643 7 5.7501 7 5.3359 7.3358 5.0001 7.75 5.0001H11Z"
                                            style={{
                                                fillRule: "nonzero",
                                                fill: "#757575",
                                            }}
                                        />
                                        <path
                                            d="M0.75 6.75C1.1642 6.75 1.5 7.0858 1.5 7.5 1.5 10.5318 3.9682 13 7 13 10.0318 13 12.5 10.5318 12.5 7.5 12.5 7.0858 12.8358 6.75 13.25 6.75 13.6642 6.75 14 7.0858 14 7.5 14 11.1069 11.2588 14.0848 7.75 14.4601V16.5H10.25C10.6642 16.5 11 16.8358 11 17.25 11 17.6642 10.6642 18 10.25 18H3.75C3.3358 18 3 17.6642 3 17.25 3 16.8358 3.3358 16.5 3.75 16.5H6.25V14.4601C2.7412 14.0848 0 11.1069 0 7.5 0 7.0858 0.3358 6.75 0.75 6.75Z"
                                            style={{
                                                fillRule: "nonzero",
                                                fill: "#757575",
                                            }}
                                        />
                                    </g>
                                </svg>
                            </div>
                        </div>
                        <div
                            style={{
                                overflow: "hidden",
                                left: 12,
                                top: "calc(-12px + 50%)",
                                width: 24,
                                height: 24,
                                position: "absolute",
                            }}
                        >
                            <img
                                data-figma-node-id="384:8407"
                                data-figma-asset="Group"
                                src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788578645/figma-screens/batch_mtntjjr9_jvgvd/frame/assets/group-2.svg"
                                alt=""
                                width={18}
                                height={18}
                                style={{
                                    left: "13.9%",
                                    top: "13.9%",
                                    right: "13.9%",
                                    bottom: "13.9%",
                                    width: "72.2%",
                                    height: "72.2%",
                                    position: "absolute",
                                }}
                            />
                        </div>
                    </label>
                    <div
                        style={{
                            overflowY: "auto",
                            overflowX: "hidden",
                            left: "calc(50% - 300px)",
                            top: 76,
                            bottom: 108,
                            width: 600,
                            position: "absolute",
                        }}
                    >
                        <div
                            style={{
                                display: "flex",
                                flexDirection: "column",
                                rowGap: 24,
                                alignItems: "stretch",
                                justifyContent: "flex-start",
                                width: 600,
                                position: "relative",
                            }}
                        >
                            <div
                                style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    rowGap: 18,
                                    alignItems: "start",
                                    width: 600,
                                }}
                            >
                                <div
                                    style={{
                                        display: "flex",
                                        flexDirection: "row",
                                        gridColumnGap: 6,
                                        alignItems: "center",
                                        justifyContent: "flex-start",
                                        width: "min-content",
                                        position: "relative",
                                        flexShrink: 0,
                                    }}
                                >
                                    <div
                                        style={{
                                            borderRadius: 24,
                                            backgroundColor: "#fd304f",
                                            overflow: "hidden",
                                            width: 37,
                                            height: 36,
                                            position: "relative",
                                            flexShrink: 0,
                                        }}
                                    >
                                        <img
                                            data-figma-node-id="384:8415"
                                            data-figma-asset="Vector"
                                            src="https://res.cloudinary.com/dsxwnm3ib/image/upload/v1788578597/figma-screens/batch_mtntil4u_vvlj8/frame-1000009486/assets/vector.svg"
                                            alt=""
                                            width={25}
                                            height={24}
                                            style={{
                                                left: "13.6%",
                                                top: "13.5%",
                                                right: "13.9%",
                                                bottom: "13.9%",
                                                width: "72.5%",
                                                height: "72.7%",
                                                position: "absolute",
                                            }}
                                        />
                                        <div
                                            style={{
                                                overflow: "hidden",
                                                left: 15.7,
                                                top: 11.7,
                                                width: 11.1,
                                                height: 6.3,
                                                position: "absolute",
                                            }}
                                        >
                                            <div
                                                style={{
                                                    borderRadius: "50%",
                                                    backgroundColor: "#000",
                                                    left: 0,
                                                    top: 0,
                                                    width: 3.7,
                                                    height: 6.3,
                                                    position: "absolute",
                                                }}
                                            />
                                            <div
                                                style={{
                                                    borderRadius: "50%",
                                                    backgroundColor: "#000",
                                                    left: 7.4,
                                                    top: 0,
                                                    width: 3.7,
                                                    height: 6.3,
                                                    position: "absolute",
                                                }}
                                            />
                                        </div>
                                    </div>
                                    <span
                                        className="text"
                                        style={{
                                            display: "inline",
                                            textAlign: "left",
                                            fontSize: 18,
                                            fontFamily:
                                                '"Open Runde", Inter, system-ui, sans-serif',
                                            fontWeight: 600,
                                            fontStretch: "100%",
                                            letterSpacing: "-0.80px",
                                            lineHeight: "100%",
                                            color: "#121212",
                                            width: "max-content",
                                            position: "relative",
                                            flexShrink: 0,
                                        }}
                                    >
                                        Sally
                                    </span>
                                </div>
                                <span
                                    className="text"
                                    style={{
                                        display: "inline",
                                        textAlign: "left",
                                        lineHeight: "22px",
                                        fontSize: 16,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 500,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.49px",
                                        color: "#121212",
                                        width: 600,
                                        position: "relative",
                                        flexShrink: 0,
                                    }}
                                >
                                    Welcome! I am your ally, and I am thrilled to
                                    help you make your day easier, more productive,
                                    and fun. Think of me as your always-available
                                    partner for brainstorming, writing, learning,
                                    and organising. <br />
                                    <br />
                                    No task is too big or too small, and I am
                                    constantly learning new ways to assist you
                                    better. Let us collaborate and build something
                                    great together.
                                </span>
                            </div>
                            <div
                                style={{
                                    borderRadius: 30,
                                    backgroundColor: "#ff2d55",
                                    display: "flex",
                                    flexDirection: "column",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    alignSelf: "flex-end",
                                    boxSizing: "border-box",
                                    width: "fit-content",
                                    maxWidth: 279,
                                    padding: "10px 12px",
                                }}
                            >
                                <span
                                    className="text"
                                    style={{
                                        display: "block",
                                        textAlign: "left",
                                        lineHeight: "18.2px",
                                        fontSize: 14,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 500,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.47px",
                                        color: "#fff",
                                        whiteSpace: "pre-wrap",
                                    }}
                                >
                                    i want a sandwich
                                </span>
                            </div>
                            <span
                                className="text"
                                style={{
                                    display: "inline",
                                    textAlign: "left",
                                    lineHeight: "22px",
                                    fontSize: 16,
                                    fontFamily:
                                        '"Open Runde", Inter, system-ui, sans-serif',
                                    fontWeight: 500,
                                    fontStretch: "100%",
                                    letterSpacing: "-0.49px",
                                    color: "#121212",
                                    width: 600,
                                }}
                            >
                                Okay. What kind of sandwich do you want and which
                                store would you like to order from?{" "}
                            </span>
                            <div
                                style={{
                                    borderRadius: 20,
                                    backgroundColor: "#ff2d55",
                                    display: "flex",
                                    flexDirection: "column",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    alignSelf: "flex-end",
                                    boxSizing: "border-box",
                                    width: "fit-content",
                                    maxWidth: 279,
                                    padding: "10px 12px",
                                }}
                            >
                                <span
                                    className="text"
                                    style={{
                                        display: "block",
                                        textAlign: "left",
                                        lineHeight: "18.2px",
                                        fontSize: 14,
                                        fontFamily:
                                            '"Open Runde", Inter, system-ui, sans-serif',
                                        fontWeight: 500,
                                        fontStretch: "100%",
                                        letterSpacing: "-0.49px",
                                        color: "#fff",
                                        whiteSpace: "pre-wrap",
                                    }}
                                >
                                    i don’t know but check their menu, i only get
                                    their 6 inch subs, i think i want the chicken
                                    sub but let me what’s available
                                </span>
                            </div>
                            <span
                                className="text"
                                style={{
                                    display: "inline",
                                    textAlign: "left",
                                    lineHeight: "22px",
                                    fontSize: 16,
                                    fontFamily:
                                        '"Open Runde", Inter, system-ui, sans-serif',
                                    fontWeight: 500,
                                    fontStretch: "100%",
                                    letterSpacing: "-0.49px",
                                    color: "#121212",
                                    width: 600,
                                }}
                            >
                                Got it! I’ll look for citysubs and let you know
                                what’s on their menu.
                            </span>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
