package com.bililearn.app.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalView
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.core.view.WindowCompat

private val DarkColorScheme = darkColorScheme(
    primary = PrimaryOrange,
    secondary = PurpleAccent,
    background = DarkBgPrimary,
    surface = DarkBgCard,
    onPrimary = DarkTextPrimary,
    onBackground = DarkTextPrimary,
    onSurface = DarkTextPrimary
)

private val LightColorScheme = lightColorScheme(
    primary = PrimaryOrange,
    secondary = PurpleAccent,
    background = LightBgPrimary,
    surface = LightBgCard,
    onPrimary = LightTextPrimary,
    onBackground = LightTextPrimary,
    onSurface = LightTextPrimary
)

@Composable
fun BiliLearnTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    hasBackground: Boolean = false,
    content: @Composable () -> Unit
) {
    val baseScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    val colorScheme = if (hasBackground) {
        baseScheme.copy(
            background = baseScheme.background.copy(alpha = 0.88f),
            surface = baseScheme.surface.copy(alpha = 0.94f)
        )
    } else {
        baseScheme
    }
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography.copy(
            titleLarge = Typography.titleLarge.copy(letterSpacing = androidx.compose.ui.unit.TextUnit.Unspecified),
            headlineSmall = Typography.headlineSmall.copy(letterSpacing = androidx.compose.ui.unit.TextUnit.Unspecified)
        ),
        shapes = Shapes(
            extraSmall = RoundedCornerShape(4.dp),
            small = RoundedCornerShape(6.dp),
            medium = RoundedCornerShape(8.dp),
            large = RoundedCornerShape(10.dp),
            extraLarge = RoundedCornerShape(12.dp)
        ),
        content = content
    )
}
