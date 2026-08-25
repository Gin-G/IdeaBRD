# JGit looks plugins up by name through the service loader, so the classes have
# to survive shrinking even though nothing references them directly.
-keep class org.eclipse.jgit.** { *; }
-dontwarn org.eclipse.jgit.**
-dontwarn javax.naming.**
-dontwarn org.slf4j.**

# Capacitor finds plugin methods by reflection.
-keep @com.getcapacitor.annotation.CapacitorPlugin class * { *; }
-keep class net.nickknows.ideabrd.** { *; }
