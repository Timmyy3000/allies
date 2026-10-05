"use client";

import { Artboard } from "@/components/artboard";
import { type AllyShape } from "@/components/ally-avatar";
import { PersistentAllyAvatar } from "./persistent-ally";

export function AllowNotifications({
  shape,
  color,
  onLater,
  onAllow,
}: {
  shape: AllyShape;
  color: string;
  onLater: () => void;
  onAllow: () => void | Promise<void>;
}) {
  return (
    <Artboard>
      <div
        data-testid="allow-notifications-allies"
        className="onboarding-page waitlist-auth-notifications"
      >
        <div className="waitlist-auth-notifications-main">
          <div className="waitlist-auth-notifications-preview">
            <div
              className="waitlist-auth-notifications-mark"
              style={{ backgroundColor: color }}
            >
              <PersistentAllyAvatar
                shape={shape}
                color={color}
                state="idle"
                size={24}
                artworkSize="full"
                sharedLayout={false}
                motionMode="system"
                label="Notification preview"
              />
            </div>
            <div className="waitlist-auth-notifications-skeleton">
              <span />
              <span />
            </div>
          </div>
          <div className="waitlist-auth-notifications-copy">
            <h1>Keep up with your allies</h1>
            <p>
              Allow notifications so you can track tasks, reminders, and reach
              goals faster
            </p>
          </div>
        </div>

        <div className="waitlist-auth-notifications-actions">
          <button
            type="button"
            data-testid="notifications-later"
            onClick={onLater}
            className="waitlist-auth-notifications-later"
          >
            I’ll do this later
          </button>
          <button
            type="button"
            data-testid="notifications-allow"
            onClick={() => void onAllow()}
            className="waitlist-auth-notifications-allow"
            style={{ backgroundColor: color }}
          >
            Allow notifications
          </button>
        </div>
      </div>
    </Artboard>
  );
}
