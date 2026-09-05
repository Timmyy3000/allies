"use client";

import type { ReactNode } from "react";

import { AllyAvatar } from "../../../components/ally-avatar";

type MobileHomeRosterExactProps = {
    actions?: ReactNode;
    tabs?: ReactNode;
    allies?: ReactNode;
    createControl?: ReactNode;
    onCreate?: () => void;
    onOpenConversation?: () => void;
};

export function MobileHomeRosterExact({
    actions,
    tabs,
    allies,
    createControl,
    onCreate,
    onOpenConversation,
}: MobileHomeRosterExactProps) {
    return (
        <div
            style={{
                backgroundColor: "#fff",
                overflow: "hidden",
                width: "100%",
                height: "100%",
                position: "relative",
                fontFamily: "var(--font-open-runde), sans-serif",
            }}
        >
            <div
                style={{
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    left: 20,
                    right: 21,
                    top: 20,
                    height: 40,
                    position: "absolute",
                    zIndex: 2,
                }}
            >
                <div
                    style={{
                        display: "flex",
                        flexDirection: "row",
                        columnGap: 18,
                        alignItems: "center",
                        minWidth: 0,
                    }}
                >
                    {tabs ?? <DefaultTabs />}
                </div>
                <div
                    style={{
                        display: "flex",
                        flexDirection: "row",
                        columnGap: 12,
                        alignItems: "center",
                        flexShrink: 0,
                    }}
                >
                    {actions ?? <DefaultActions onCreate={onCreate} />}
                </div>
            </div>

            <div
                style={{
                    left: 20,
                    top: 131,
                    right: 20,
                    bottom: 130,
                    position: "absolute",
                    overflowX: "hidden",
                    overflowY: "auto",
                }}
            >
                {allies ?? <DefaultAllyRow onOpen={onOpenConversation} />}
            </div>

            <div
                style={{
                    left: 20,
                    bottom: 58,
                    width: 162,
                    height: 48,
                    position: "absolute",
                    zIndex: 2,
                }}
            >
                {createControl ?? <DefaultCreateControl onCreate={onCreate} />}
            </div>
        </div>
    );
}

function DefaultActions({ onCreate }: { onCreate?: () => void }) {
    return (
        <>
            <RosterIconButton background="rgba(251,136,0,0.15)" onClick={onCreate} label="Meet another Ally">
                <img
                    src="/home/mobile-roster/chef.svg"
                    alt=""
                    width={24}
                    height={24}
                    style={{ width: 24, height: 24 }}
                />
            </RosterIconButton>
            <RosterIconButton background="#f3f3f3">
                <img
                    src="/home/mobile-roster/search.svg"
                    alt=""
                    width={24}
                    height={24}
                    style={{ width: 19, height: 19 }}
                />
            </RosterIconButton>
            <div
                style={{
                    overflow: "hidden",
                    width: 40,
                    height: 40,
                    position: "relative",
                    flexShrink: 0,
                }}
            >
                <div
                    style={{
                        borderRadius: "50%",
                        backgroundColor: "#f3f3f3",
                        inset: 0,
                        position: "absolute",
                    }}
                />
                <span
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        inset: 0,
                        position: "absolute",
                        fontSize: 20,
                        fontWeight: 600,
                        letterSpacing: -0.5,
                        color: "#000",
                        lineHeight: "120%",
                    }}
                >
                    SD
                </span>
            </div>
        </>
    );
}

function DefaultTabs() {
    return (
        <>
            <div
                style={{
                    borderRadius: 100,
                    backgroundColor: "#ff5800",
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "min-content",
                    position: "relative",
                    flexShrink: 0,
                    padding: "8px 12px",
                }}
            >
                <span
                    style={{
                        fontSize: 14,
                        fontWeight: 600,
                        letterSpacing: -0.62,
                        color: "#fff",
                        lineHeight: "120%",
                        whiteSpace: "nowrap",
                    }}
                >
                    My allies
                </span>
            </div>
            <span
                style={{
                    fontSize: 14,
                    fontWeight: 600,
                    letterSpacing: -0.58,
                    color: "#757575",
                    lineHeight: "120%",
                    whiteSpace: "nowrap",
                }}
            >
                Events
            </span>
        </>
    );
}

function DefaultAllyRow({ onOpen }: { onOpen?: () => void }) {
    return (
        <button
            type="button"
            onClick={onOpen}
            aria-label="Open Sally Morano conversation"
            style={{
                display: "flex",
                flexDirection: "row",
                columnGap: 12,
                alignItems: "center",
                justifyContent: "flex-start",
                width: "100%",
                padding: 0,
                border: 0,
                background: "transparent",
                cursor: "pointer",
                font: "inherit",
                textAlign: "left",
            }}
        >
            <div
                style={{
                    width: 48,
                    height: 48,
                    position: "relative",
                    flexShrink: 0,
                }}
            >
                <AllyAvatar shape="ghosty" color="#fd304f" size={48} state="idle" label="" />
                <div
                    style={{
                        borderWidth: 1,
                        borderStyle: "solid",
                        borderColor: "#fff",
                        borderRadius: "50%",
                        backgroundColor: "#12c25b",
                        right: 0,
                        bottom: 0,
                        width: 10,
                        height: 10,
                        position: "absolute",
                    }}
                />
            </div>
            <div
                style={{
                    display: "flex",
                    flexDirection: "column",
                    rowGap: 6,
                    alignItems: "start",
                    minWidth: 0,
                    flex: 1,
                }}
            >
                <span
                    style={{
                        fontSize: 18,
                        fontWeight: 600,
                        letterSpacing: -0.92,
                        color: "#121212",
                        lineHeight: "120%",
                    }}
                >
                    Sally Morano
                </span>
                <span
                    style={{
                        fontSize: 14,
                        fontWeight: 500,
                        letterSpacing: -0.48,
                        color: "#757575",
                        lineHeight: "120%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        width: "100%",
                    }}
                >
                    Welcome! I am your ally, and I am thrilled to announce
                </span>
            </div>
        </button>
    );
}

function DefaultCreateControl({ onCreate }: { onCreate?: () => void }) {
    return (
        <button
            type="button"
            onClick={onCreate}
            aria-label="Make an Ally"
            style={{
                borderRadius: 60,
                backgroundColor: "#ff5800",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 162,
                height: 48,
                padding: 10,
                border: 0,
                cursor: "pointer",
            }}
        >
            <span
                style={{
                    fontSize: 18,
                    fontWeight: 600,
                    letterSpacing: -0.64,
                    color: "#fff",
                    lineHeight: "120%",
                    whiteSpace: "nowrap",
                }}
            >
                Make an ally
            </span>
        </button>
    );
}

function RosterIconButton({
    background,
    children,
    onClick,
    label,
}: {
    background: string;
    children: ReactNode;
    onClick?: () => void;
    label?: string;
}) {
    const inner = (
        <div
            style={{
                overflow: "hidden",
                width: 40,
                height: 40,
                position: "relative",
                flexShrink: 0,
            }}
        >
            <div
                style={{
                    borderRadius: "50%",
                    backgroundColor: background,
                    inset: 0,
                    position: "absolute",
                }}
            />
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    left: 8,
                    top: 8,
                    width: 24,
                    height: 24,
                    position: "absolute",
                }}
            >
                {children}
            </div>
        </div>
    );

    if (!onClick) return inner;

    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={label}
            style={{
                padding: 0,
                border: 0,
                background: "transparent",
                cursor: "pointer",
            }}
        >
            {inner}
        </button>
    );
}
